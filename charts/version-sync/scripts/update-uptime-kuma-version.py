#!/usr/bin/env python3
"""
Script to dynamically update Uptime Kuma monitor tags with version from version.txt endpoints.

This script uses Socket.io directly to communicate with Uptime Kuma's API.
According to https://github.com/louislam/uptime-kuma/wiki/API-Documentation,
Uptime Kuma primarily uses Socket.io for real-time communication.

This script:
1. Fetches versions from multiple service endpoints
2. Connects to Uptime Kuma via Socket.io
3. Updates Uptime Kuma monitors with version tags using Socket.io events
4. Can be run as a CronJob in Kubernetes
5. Requires SERVICES_CONFIG environment variable with JSON array of services
"""

import os
import sys
import requests
import json
import socketio
import threading
import time
from typing import Optional, List, Dict, Any
from queue import Queue

# Configuration from environment variables
UPTIME_KUMA_URL = os.getenv('UPTIME_KUMA_URL', 'http://uptime-kuma.uptime-kuma.svc.cluster.local:3001')
UPTIME_KUMA_USERNAME = os.getenv('UPTIME_KUMA_USERNAME', '')
UPTIME_KUMA_PASSWORD = os.getenv('UPTIME_KUMA_PASSWORD', '')
UPTIME_KUMA_API_TOKEN = os.getenv('UPTIME_KUMA_API_TOKEN', '')
VERIFY_SSL = os.getenv('VERIFY_SSL', 'false').lower() == 'true'

# Services configuration (JSON format)
SERVICES_CONFIG = os.getenv('SERVICES_CONFIG', '')


def get_version(version_endpoint: str) -> Optional[str]:
    """Fetch version from the version endpoint."""
    try:
        response = requests.get(version_endpoint, timeout=10, verify=VERIFY_SSL)
        response.raise_for_status()
        version = response.text.strip()
        return version
    except requests.exceptions.RequestException as e:
        print(f"✗ Error fetching version from {version_endpoint}: {e}", file=sys.stderr)
        return None


class UptimeKumaClient:
    """Client for interacting with Uptime Kuma via Socket.io."""
    
    def __init__(self, url: str, verify_ssl: bool = False):
        self.url = url
        self.verify_ssl = verify_ssl
        self.sio = socketio.Client()
        self.connected = False
        self.authenticated = False
        self.response_queue = Queue()
        self.event_data = {}
        self.lock = threading.Lock()
        
        # Set up event handlers
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Set up Socket.io event handlers."""
        
        @self.sio.on('connect')
        def on_connect():
            self.connected = True
            print("✓ Connected to Uptime Kuma Socket.io")
        
        @self.sio.on('disconnect')
        def on_disconnect():
            self.connected = False
            self.authenticated = False
            print("⚠ Disconnected from Uptime Kuma Socket.io")
            # Put disconnect event in queue so login can detect it
            self.response_queue.put({'disconnected': True})
        
        @self.sio.on('connect_error')
        def on_connect_error(data):
            print(f"✗ Connection error: {data}", file=sys.stderr)
            self.response_queue.put({'error': str(data)})
        
        @self.sio.on('error')
        def on_error(data):
            print(f"✗ Socket.io error: {data}", file=sys.stderr)
            self.response_queue.put({'error': str(data)})
        
        @self.sio.on('exception')
        def on_exception(data):
            print(f"✗ Server exception: {data}", file=sys.stderr)
            self.response_queue.put({'error': str(data)})
        
        @self.sio.on('*')
        def catch_all(event, *args):
            # Silently handle events - only log if needed for debugging
            pass
        
        # Generic response handler - will be used for callbacks
        # Note: We'll use specific callbacks for each operation instead of queue
        
        # Data event handlers (monitorList, tagList, etc.)
        @self.sio.on('monitorList')
        def on_monitor_list(data):
            with self.lock:
                self.event_data['monitorList'] = data
        
        @self.sio.on('tagList')
        def on_tag_list(data):
            with self.lock:
                self.event_data['tagList'] = data
        
        @self.sio.on('updateMonitorIntoList')
        def on_update_monitor(data):
            if isinstance(data, dict):
                # Update cached monitor list
                with self.lock:
                    if 'monitorList' in self.event_data:
                        for monitor_id, monitor_data in data.items():
                            self.event_data['monitorList'][monitor_id] = monitor_data
    
    def connect(self) -> bool:
        """Connect to Uptime Kuma Socket.io server."""
        try:
            print(f"Connecting to Uptime Kuma at {self.url}...")
            self.sio.connect(self.url, wait_timeout=10)
            
            # Wait for connection
            timeout = 5
            start_time = time.time()
            while not self.connected and (time.time() - start_time) < timeout:
                time.sleep(0.1)
            
            if not self.connected:
                print("✗ Connection timeout", file=sys.stderr)
                return False
            
            return True
        except Exception as e:
            print(f"✗ Error connecting: {e}", file=sys.stderr)
            return False
    
    def login(self, username: str, password: str) -> bool:
        """Authenticate with Uptime Kuma."""
        if not self.connected:
            print("✗ Not connected", file=sys.stderr)
            return False
        
        try:
            # Wait a bit for connection to stabilize (Socket.io needs time to establish)
            time.sleep(1.0)
            
            # Verify we're still connected
            if not self.connected:
                print("✗ Connection lost before authentication", file=sys.stderr)
                return False
            
            # Clear any previous responses
            while not self.response_queue.empty():
                try:
                    self.response_queue.get_nowait()
                except:
                    break
            
            # Set up a flag to track if we got a response
            login_response_received = False
            login_success = False
            login_error = None
            
            # Callback function for Socket.io emit
            def login_callback(response):
                nonlocal login_response_received, login_success, login_error
                login_response_received = True
                if isinstance(response, dict):
                    if response.get('ok'):
                        login_success = True
                    else:
                        login_error = response.get('msg', 'Authentication failed')
                else:
                    # Handle non-dict responses
                    login_error = f"Unexpected response type: {type(response)}"
            
            # Verify we have credentials
            if not password:
                print("✗ Error: Password is empty", file=sys.stderr)
                return False
            
            # Send login event with callback
            print(f"Attempting to authenticate as user: {username if username else '(empty)'}")
            try:
                # According to API docs, login event format is: {username, password, token?}
                # Note: token is optional (for 2FA)
                login_data = {
                    'username': username if username else '',  # Ensure it's a string, not None
                    'password': password
                }
                
                # Use callback parameter instead of waiting for 'res' event
                self.sio.emit('login', login_data, callback=login_callback)
                
                # Give it a moment to process
                time.sleep(0.2)
            except Exception as e:
                print(f"✗ Error sending login event: {e}", file=sys.stderr)
                import traceback
                traceback.print_exc()
                return False
            
            # Wait for response with longer timeout
            timeout = 10
            start_time = time.time()
            disconnected = False
            server_error = None
            
            while (time.time() - start_time) < timeout:
                if login_response_received:
                    break
                # Check if we got disconnected
                if not self.connected:
                    disconnected = True
                    print("⚠ Connection lost during authentication", file=sys.stderr)
                    break
                # Check for errors in queue
                try:
                    while not self.response_queue.empty():
                        item = self.response_queue.get_nowait()
                        if 'error' in item:
                            server_error = item['error']
                            print(f"✗ Server error: {server_error}", file=sys.stderr)
                            break
                except:
                    pass
                if server_error:
                    break
                time.sleep(0.1)
            
            if disconnected or server_error:
                if disconnected:
                    print("✗ Connection disconnected during authentication", file=sys.stderr)
                    print("   This usually means the server rejected the login attempt", file=sys.stderr)
                if server_error:
                    print(f"✗ Server reported error: {server_error}", file=sys.stderr)
                print("   Please verify:", file=sys.stderr)
                print("   1. Username and password are correct", file=sys.stderr)
                print("   2. The account is not locked", file=sys.stderr)
                print("   3. The account has proper permissions", file=sys.stderr)
                return False
            
            if not login_response_received:
                print("✗ Authentication timeout - no response received", file=sys.stderr)
                print("   This might indicate:", file=sys.stderr)
                print("   - Incorrect username/password", file=sys.stderr)
                print("   - Network connectivity issues", file=sys.stderr)
                print("   - Uptime Kuma server not responding", file=sys.stderr)
                return False
            
            if login_success:
                self.authenticated = True
                print("✓ Authenticated successfully")
                
                # Wait a moment to see if server sends any automatic data
                time.sleep(1.0)
                
                return True
            else:
                error_msg = login_error or 'Authentication failed'
                print(f"✗ Authentication failed: {error_msg}", file=sys.stderr)
                return False
        except Exception as e:
            print(f"✗ Error during authentication: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return False
    
    def get_monitors(self) -> Optional[Dict[str, Any]]:
        """Get list of monitors."""
        if not self.authenticated:
            print("✗ Not authenticated", file=sys.stderr)
            return None
        
        try:
            # Check if we already have the monitor list (sent automatically after auth)
            with self.lock:
                if 'monitorList' in self.event_data:
                    return self.event_data['monitorList']
            
            # If not, request it
            self.sio.emit('monitorList')
            
            # Wait for response
            timeout = 5
            start_time = time.time()
            while (time.time() - start_time) < timeout:
                with self.lock:
                    if 'monitorList' in self.event_data:
                        return self.event_data['monitorList']
                time.sleep(0.1)
            
            print("✗ Timeout waiting for monitor list", file=sys.stderr)
            return None
        except Exception as e:
            print(f"✗ Error getting monitors: {e}", file=sys.stderr)
            return None
    
    def get_tags(self) -> Optional[List[Dict[str, Any]]]:
        """Get list of tags."""
        if not self.authenticated:
            print("✗ Not authenticated", file=sys.stderr)
            return None
        
        try:
            # Check if we already have the tag list (sent automatically after auth)
            with self.lock:
                if 'tagList' in self.event_data:
                    tag_list = self.event_data['tagList']
                    # Ensure we return a list, not None
                    return tag_list if isinstance(tag_list, list) else []
            
            # If not, request it using callback pattern
            response_received = False
            response_data = None
            
            def tag_list_callback(response):
                nonlocal response_received, response_data
                response_received = True
                if isinstance(response, list):
                    response_data = response
                elif isinstance(response, dict):
                    # Some APIs return tags in a dict format
                    if 'tags' in response:
                        response_data = response['tags']
                    elif 'ok' in response and response.get('ok'):
                        # Success but no tags yet - return empty list
                        response_data = []
                    else:
                        response_data = []
                else:
                    response_data = []
            
            # Request tag list with callback
            self.sio.emit('tagList', callback=tag_list_callback)
            
            # Wait for response
            timeout = 5
            start_time = time.time()
            while (time.time() - start_time) < timeout:
                if response_received:
                    break
                time.sleep(0.1)
            
            if not response_received:
                # If timeout, assume no tags exist yet and return empty list
                # This allows the script to proceed and create the first tag
                return []
            
            # Also check if tagList event was received (some servers send both)
            with self.lock:
                if 'tagList' in self.event_data:
                    cached_list = self.event_data['tagList']
                    if isinstance(cached_list, list):
                        # Use the cached version if it's more complete
                        if len(cached_list) > len(response_data if response_data else []):
                            return cached_list
            
            result = response_data if response_data is not None else []
            return result
        except Exception as e:
            print(f"✗ Error getting tags: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            # Return empty list on error to allow script to continue
            return []
    
    def add_tag(self, name: str, color: str = '#3b82f6') -> Optional[Dict[str, Any]]:
        """Create a new tag."""
        if not self.authenticated:
            print("✗ Not authenticated", file=sys.stderr)
            return None
        
        try:
            # Set up response tracking
            response_received = False
            response_data = None
            response_error = None
            
            def tag_callback(response):
                nonlocal response_received, response_data, response_error
                response_received = True
                if isinstance(response, dict):
                    if response.get('ok'):
                        response_data = response.get('tag')
                    else:
                        response_error = response.get('msg', 'Failed to create tag')
                else:
                    response_error = f"Unexpected response type: {type(response)}"
            
            # Send addTag event with callback
            self.sio.emit('addTag', {
                'name': name,
                'color': color
            }, callback=tag_callback)
            
            # Wait for response
            timeout = 5
            start_time = time.time()
            while (time.time() - start_time) < timeout:
                if response_received:
                    break
                time.sleep(0.1)
            
            if not response_received:
                print("✗ Timeout creating tag", file=sys.stderr)
                return None
            
            if response_error:
                print(f"✗ Error creating tag: {response_error}", file=sys.stderr)
                return None
            
            return response_data
        except Exception as e:
            print(f"✗ Error creating tag: {e}", file=sys.stderr)
            return None
    
    def edit_monitor(self, monitor_data: Dict[str, Any]) -> bool:
        """Update a monitor."""
        if not self.authenticated:
            print("✗ Not authenticated", file=sys.stderr)
            return False
        
        try:
            # Set up response tracking
            response_received = False
            response_success = False
            response_error = None
            
            def edit_callback(response):
                nonlocal response_received, response_success, response_error
                response_received = True
                if isinstance(response, dict):
                    if response.get('ok'):
                        response_success = True
                    else:
                        response_error = response.get('msg', 'Failed to update monitor')
                else:
                    response_error = f"Unexpected response type: {type(response)}"
            
            # Send editMonitor event with callback
            self.sio.emit('editMonitor', monitor_data, callback=edit_callback)
            
            # Wait for response
            timeout = 5
            start_time = time.time()
            while (time.time() - start_time) < timeout:
                if response_received:
                    break
                time.sleep(0.1)
            
            if not response_received:
                print("✗ Timeout updating monitor", file=sys.stderr)
                return False
            
            if response_error:
                print(f"✗ Error updating monitor: {response_error}", file=sys.stderr)
                return False
            
            return response_success
        except Exception as e:
            print(f"✗ Error updating monitor: {e}", file=sys.stderr)
            return False
    
    def disconnect(self):
        """Disconnect from Uptime Kuma."""
        if self.connected:
            self.sio.disconnect()


def get_or_create_tag(client: UptimeKumaClient, tag_name: str, tag_color: str = '#3b82f6') -> Optional[int]:
    """Get or create a tag and return its ID."""
    try:
        # Get all tags
        tags = client.get_tags()
        if tags is None:
            return None
        
        # Check if tag exists
        for tag in tags:
            if tag.get('name', '') == tag_name:
                tag_id = tag.get('id')
                print(f"✓ Found existing tag '{tag_name}'")
                return tag_id
        
        # Create new tag
        print(f"Creating new tag '{tag_name}'...")
        new_tag = client.add_tag(name=tag_name, color=tag_color)
        if new_tag:
            tag_id = new_tag.get('id')
            print(f"✓ Created tag '{tag_name}'")
            return tag_id
        
        return None
    except Exception as e:
        print(f"✗ Error managing tags: {e}", file=sys.stderr)
        return None


def update_monitor_tags(client: UptimeKumaClient, monitor_id: int, monitor_name: str, version: str, tag_prefix: str = 'version') -> bool:
    """Update monitor with version tag."""
    try:
        # Get monitor list to find the monitor
        monitors = client.get_monitors()
        if monitors is None:
            return False
        
        monitor = monitors.get(str(monitor_id))
        if not monitor:
            print(f"✗ Monitor ID {monitor_id} not found", file=sys.stderr)
            return False
        
        # Get or create version tag
        version_tag_name = f'{tag_prefix}-{version}'
        version_tag_id = get_or_create_tag(client, version_tag_name)
        if not version_tag_id:
            return False
        
        # Wait a moment after creating tag to ensure it's fully available
        time.sleep(0.5)
        
        # Get current tags and all tags
        current_tags = monitor.get('tags', [])
        all_tags = client.get_tags()
        if not all_tags:
            all_tags = []
        
        # Debug: print current state
        print(f"   Debug: Current monitor tags: {current_tags}")
        print(f"   Debug: All available tags: {all_tags}")
        
        # Create a map of tag_id -> tag_info for easy lookup
        tag_map = {tag.get('id'): tag for tag in all_tags}
        
        # Filter out old version tags (tags starting with tag_prefix)
        filtered_tags = []
        for tag in current_tags:
            if isinstance(tag, dict):
                tag_name = tag.get('name', '')
                # Keep tags that don't start with the version prefix
                if tag_name and not tag_name.startswith(f'{tag_prefix}-'):
                    filtered_tags.append(tag)
            else:
                # Fallback: if tag is just an ID, convert to object
                tag_id = tag
                if tag_id in tag_map:
                    tag_info = tag_map[tag_id]
                    tag_name = tag_info.get('name', '')
                    if not tag_name.startswith(f'{tag_prefix}-'):
                        # Build tag object in the format Uptime Kuma expects
                        tag_obj = {
                            'tag_id': tag_id,
                            'name': tag_name,
                            'color': tag_info.get('color', '#3b82f6'),
                            'value': ''
                        }
                        filtered_tags.append(tag_obj)
                else:
                    # If we can't find the tag, keep it as a safety measure
                    tag_obj = {
                        'tag_id': tag_id,
                        'name': f'tag-{tag_id}',
                        'color': '#3b82f6',
                        'value': ''
                    }
                    filtered_tags.append(tag_obj)
        
        # Add new version tag as a proper object
        if version_tag_id in tag_map:
            version_tag_info = tag_map[version_tag_id]
            version_tag_obj = {
                'tag_id': version_tag_id,
                'name': version_tag_info.get('name', version_tag_name),
                'color': version_tag_info.get('color', '#3b82f6'),
                'value': ''
            }
        else:
            # If tag not in map yet (just created), build it manually
            version_tag_obj = {
                'tag_id': version_tag_id,
                'name': version_tag_name,
                'color': '#3b82f6',
                'value': ''
            }
        filtered_tags.append(version_tag_obj)
        
        # Update monitor with new tags
        monitor_data = monitor.copy()
        monitor_data['tags'] = filtered_tags
        
        # Debug: print what we're sending
        print(f"   Debug: Sending tags to API: {filtered_tags}")
        
        success = client.edit_monitor(monitor_data)
        if success:
            # Wait a moment for the update to propagate
            time.sleep(1.0)
            
            # Verify the update
            updated_monitors = client.get_monitors()
            if updated_monitors:
                updated_monitor = updated_monitors.get(str(monitor_id))
                if updated_monitor:
                    updated_tags = updated_monitor.get('tags', [])
                    
                    # Debug: print tag structure
                    print(f"   Debug: Updated tags structure: {updated_tags}")
                    
                    # Try multiple ways to extract tag IDs and names
                    updated_tag_ids = []
                    updated_tag_names = []
                    for tag in updated_tags:
                        if isinstance(tag, dict):
                            # Try both 'tag_id' and 'id' keys
                            tag_id = tag.get('tag_id') or tag.get('id')
                            if tag_id:
                                updated_tag_ids.append(tag_id)
                            if 'name' in tag:
                                updated_tag_names.append(tag.get('name'))
                        else:
                            # If it's just an ID
                            updated_tag_ids.append(tag)
                    
                    print(f"   Debug: Extracted tag IDs: {updated_tag_ids}")
                    print(f"   Debug: Extracted tag names: {updated_tag_names}")
                    print(f"   Debug: Looking for tag ID: {version_tag_id}, tag name: {version_tag_name}")
                    
                    if version_tag_id in updated_tag_ids or version_tag_name in updated_tag_names:
                        print(f"✓ Successfully updated monitor '{monitor_name}' with tag '{version_tag_name}'")
                    else:
                        print(f"⚠ Warning: Tag '{version_tag_name}' not found in monitor tags after update", file=sys.stderr)
        
        return success
    except Exception as e:
        print(f"✗ Error updating monitor '{monitor_name}': {e}", file=sys.stderr)
        return False


def process_service(client: UptimeKumaClient, service_config: Dict[str, str]) -> bool:
    """Process a single service configuration."""
    monitor_name = service_config.get('monitorName', '')
    version_endpoint = service_config.get('versionEndpoint', '')
    tag_prefix = service_config.get('tagPrefix', 'version')
    
    if not monitor_name or not version_endpoint:
        print(f"✗ Invalid service config: missing monitorName or versionEndpoint", file=sys.stderr)
        return False
    
    print(f"\n📦 Processing service: {monitor_name}")
    print(f"   Endpoint: {version_endpoint}")
    
    # Fetch version
    version = get_version(version_endpoint)
    if not version:
        return False
    
    print(f"   ✓ Fetched version: {version}")
    
    # Get monitor list and find monitor by name
    monitors = client.get_monitors()
    if monitors is None:
        print(f"   ✗ Failed to retrieve monitor list from Uptime Kuma")
        return False
    
    monitor_id = None
    for mid, monitor in monitors.items():
        if monitor.get('name', '') == monitor_name:
            monitor_id = int(mid)
            break
    
    if not monitor_id:
        print(f"   ✗ Monitor '{monitor_name}' not found", file=sys.stderr)
        return False
    
    print(f"   ✓ Found monitor")
    
    # Update tags
    success = update_monitor_tags(client, monitor_id, monitor_name, version, tag_prefix)
    return success


def parse_services_config() -> List[Dict[str, str]]:
    """Parse services configuration from JSON string."""
    if not SERVICES_CONFIG:
        print("✗ Error: SERVICES_CONFIG environment variable is required", file=sys.stderr)
        return []
    
    try:
        services = json.loads(SERVICES_CONFIG)
        if not isinstance(services, list):
            print("✗ Error: SERVICES_CONFIG must be a JSON array", file=sys.stderr)
            return []
        
        if len(services) == 0:
            print("✗ Error: SERVICES_CONFIG must contain at least one service", file=sys.stderr)
            return []
        
        print(f"✓ Loaded {len(services)} service(s) from SERVICES_CONFIG")
        return services
    except json.JSONDecodeError as e:
        print(f"✗ Error parsing SERVICES_CONFIG JSON: {e}", file=sys.stderr)
        return []


def main():
    """Main execution."""
    # Check authentication credentials
    if not UPTIME_KUMA_API_TOKEN and not UPTIME_KUMA_PASSWORD:
        print("✗ Error: Either UPTIME_KUMA_API_TOKEN or UPTIME_KUMA_PASSWORD must be set", file=sys.stderr)
        sys.exit(1)
    
    # Parse service configurations
    services = parse_services_config()
    if not services:
        sys.exit(1)
    
    print(f"\n🚀 Starting version sync for {len(services)} service(s)")
    print(f"   Uptime Kuma URL: {UPTIME_KUMA_URL}\n")
    
    # Create client and connect
    client = UptimeKumaClient(UPTIME_KUMA_URL, verify_ssl=VERIFY_SSL)
    
    if not client.connect():
        print("✗ Failed to connect to Uptime Kuma", file=sys.stderr)
        sys.exit(1)
    
    try:
        # Authenticate
        password = UPTIME_KUMA_API_TOKEN if UPTIME_KUMA_API_TOKEN else UPTIME_KUMA_PASSWORD
        username = UPTIME_KUMA_USERNAME if UPTIME_KUMA_USERNAME else ''
        
        if not client.login(username, password):
            print("✗ Failed to authenticate with Uptime Kuma", file=sys.stderr)
            sys.exit(1)
        
        # Process each service
        results = []
        for service_config in services:
            success = process_service(client, service_config)
            results.append(success)
        
        # Summary
        successful = sum(results)
        failed = len(results) - successful
        
        print(f"\n📊 Summary:")
        print(f"   ✓ Successful: {successful}")
        if failed > 0:
            print(f"   ✗ Failed: {failed}")
        
        # Exit with error if any service failed
        if failed > 0:
            sys.exit(1)
        
        print("\n✓ All version tags updated successfully")
        sys.exit(0)
        
    finally:
        # Always disconnect
        client.disconnect()


if __name__ == '__main__':
    main()
