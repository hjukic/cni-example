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
            print(f"DEBUG: Received event '{event}' with {len(args)} args")
            if event not in ['connect', 'disconnect', 'monitorList', 'tagList', 'heartbeat']:
                print(f"DEBUG: Event '{event}' data: {args}")
        
        # Generic response handler - will be used for callbacks
        # Note: We'll use specific callbacks for each operation instead of queue
        
        # Data event handlers (monitorList, tagList, etc.)
        @self.sio.on('monitorList')
        def on_monitor_list(data):
            print(f"DEBUG: Received monitorList event")
            print(f"DEBUG: Monitor data type: {type(data)}")
            print(f"DEBUG: Monitor data keys: {list(data.keys()) if isinstance(data, dict) else 'not a dict'}")
            if isinstance(data, dict):
                print(f"DEBUG: Number of monitors: {len(data)}")
            with self.lock:
                self.event_data['monitorList'] = data
                print(f"DEBUG: Stored monitorList in event_data")
        
        @self.sio.on('tagList')
        def on_tag_list(data):
            print(f"DEBUG: Received tagList event")
            print(f"DEBUG: Tag data type: {type(data)}")
            if isinstance(data, list):
                print(f"DEBUG: Number of tags: {len(data)}")
            with self.lock:
                self.event_data['tagList'] = data
                print(f"DEBUG: Stored tagList in event_data")
    
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
                print(f"DEBUG: Received login callback: {response}")
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
            print(f"DEBUG: Password length: {len(password)} characters")
            print("DEBUG: Sending login event with callback...")
            try:
                # According to API docs, login event format is: {username, password, token?}
                # Note: token is optional (for 2FA)
                login_data = {
                    'username': username if username else '',  # Ensure it's a string, not None
                    'password': password
                }
                print(f"DEBUG: Login data: username='{login_data['username']}', password length={len(login_data['password'])}")
                
                # Use callback parameter instead of waiting for 'res' event
                self.sio.emit('login', login_data, callback=login_callback)
                print("DEBUG: Login event sent with callback, waiting for response...")
                
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
                print("DEBUG: Waiting briefly for any automatic data from server...")
                time.sleep(1.0)
                with self.lock:
                    print(f"DEBUG: Available event_data keys after auth: {list(self.event_data.keys())}")
                
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
            print("DEBUG: get_monitors() called")
            
            # Check if we already have the monitor list (sent automatically after auth)
            with self.lock:
                if 'monitorList' in self.event_data:
                    print("DEBUG: Monitor list already available from earlier event")
                    print(f"DEBUG: Using cached monitorList with {len(self.event_data['monitorList'])} monitors")
                    return self.event_data['monitorList']
            
            # If not, request it
            print("DEBUG: Monitor list not available, requesting from server...")
            
            # Request monitor list
            print("DEBUG: Emitting 'monitorList' event to request monitors")
            self.sio.emit('monitorList')
            print("DEBUG: 'monitorList' event emitted, waiting for response...")
            
            # Wait for response
            timeout = 5
            start_time = time.time()
            check_count = 0
            while (time.time() - start_time) < timeout:
                check_count += 1
                with self.lock:
                    if 'monitorList' in self.event_data:
                        print(f"DEBUG: Received monitorList after {check_count} checks ({time.time() - start_time:.2f}s)")
                        return self.event_data['monitorList']
                time.sleep(0.1)
            
            print(f"DEBUG: Timeout after {check_count} checks ({timeout}s)", file=sys.stderr)
            print(f"DEBUG: Connected: {self.connected}, Authenticated: {self.authenticated}", file=sys.stderr)
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
            print("DEBUG: get_tags() called")
            
            # Check if we already have the tag list (sent automatically after auth)
            with self.lock:
                if 'tagList' in self.event_data:
                    print("DEBUG: Tag list already available from earlier event")
                    tag_count = len(self.event_data['tagList']) if isinstance(self.event_data['tagList'], list) else 'N/A'
                    print(f"DEBUG: Using cached tagList with {tag_count} tags")
                    return self.event_data['tagList']
            
            # If not, request it
            print("DEBUG: Tag list not available, requesting from server...")
            
            # Request tag list
            self.sio.emit('tagList')
            
            # Wait for response
            timeout = 5
            start_time = time.time()
            while (time.time() - start_time) < timeout:
                with self.lock:
                    if 'tagList' in self.event_data:
                        print(f"DEBUG: Received tagList after {time.time() - start_time:.2f}s")
                        return self.event_data['tagList']
                time.sleep(0.1)
            
            print("DEBUG: Timeout waiting for tag list", file=sys.stderr)
            print("✗ Timeout waiting for tag list", file=sys.stderr)
            return None
        except Exception as e:
            print(f"✗ Error getting tags: {e}", file=sys.stderr)
            return None
    
    def add_tag(self, name: str, color: str = '#3b82f6') -> Optional[Dict[str, Any]]:
        """Create a new tag."""
        if not self.authenticated:
            print("✗ Not authenticated", file=sys.stderr)
            return None
        
        try:
            print(f"DEBUG: add_tag() called for tag '{name}'")
            # Set up response tracking
            response_received = False
            response_data = None
            response_error = None
            
            def tag_callback(response):
                nonlocal response_received, response_data, response_error
                print(f"DEBUG: add_tag callback received: {response}")
                response_received = True
                if isinstance(response, dict):
                    if response.get('ok'):
                        response_data = response.get('tag')
                        print(f"DEBUG: Tag created successfully with ID: {response_data.get('id') if response_data else 'N/A'}")
                    else:
                        response_error = response.get('msg', 'Failed to create tag')
                        print(f"DEBUG: Tag creation failed: {response_error}")
                else:
                    response_error = f"Unexpected response type: {type(response)}"
                    print(f"DEBUG: Unexpected response type: {type(response)}")
            
            # Send addTag event with callback
            print(f"DEBUG: Emitting 'addTag' event for tag '{name}'")
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
                print(f"DEBUG: Timeout waiting for addTag response after {timeout}s", file=sys.stderr)
                print("✗ Timeout creating tag", file=sys.stderr)
                return None
            
            if response_error:
                print(f"✗ Error creating tag: {response_error}", file=sys.stderr)
                return None
            
            print(f"DEBUG: Returning tag data: {response_data}")
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
            monitor_id = monitor_data.get('id', 'unknown')
            monitor_name = monitor_data.get('name', 'unknown')
            print(f"DEBUG: edit_monitor() called for monitor ID {monitor_id} ('{monitor_name}')")
            print(f"DEBUG: Monitor tags to set: {monitor_data.get('tags', [])}")
            
            # Set up response tracking
            response_received = False
            response_success = False
            response_error = None
            
            def edit_callback(response):
                nonlocal response_received, response_success, response_error
                print(f"DEBUG: edit_monitor callback received: {response}")
                response_received = True
                if isinstance(response, dict):
                    if response.get('ok'):
                        response_success = True
                        print(f"DEBUG: Monitor updated successfully")
                    else:
                        response_error = response.get('msg', 'Failed to update monitor')
                        print(f"DEBUG: Monitor update failed: {response_error}")
                else:
                    response_error = f"Unexpected response type: {type(response)}"
                    print(f"DEBUG: Unexpected response type: {type(response)}")
            
            # Send editMonitor event with callback
            print(f"DEBUG: Emitting 'editMonitor' event for monitor ID {monitor_id}")
            self.sio.emit('editMonitor', monitor_data, callback=edit_callback)
            
            # Wait for response
            timeout = 5
            start_time = time.time()
            while (time.time() - start_time) < timeout:
                if response_received:
                    break
                time.sleep(0.1)
            
            if not response_received:
                print(f"DEBUG: Timeout waiting for editMonitor response after {timeout}s", file=sys.stderr)
                print("✗ Timeout updating monitor", file=sys.stderr)
                return False
            
            if response_error:
                print(f"✗ Error updating monitor: {response_error}", file=sys.stderr)
                return False
            
            print(f"DEBUG: Returning success: {response_success}")
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
        print(f"DEBUG: get_or_create_tag() called for tag '{tag_name}'")
        # Get all tags
        tags = client.get_tags()
        if tags is None:
            print(f"DEBUG: get_tags() returned None")
            return None
        
        print(f"DEBUG: Retrieved {len(tags) if isinstance(tags, list) else 'unknown'} tags")
        
        # Check if tag exists
        for tag in tags:
            tag_name_in_list = tag.get('name', '')
            print(f"DEBUG: Checking tag: '{tag_name_in_list}' (ID: {tag.get('id')})")
            if tag_name_in_list == tag_name:
                tag_id = tag.get('id')
                print(f"✓ Found existing tag '{tag_name}' with ID: {tag_id}")
                return tag_id
        
        # Create new tag
        print(f"DEBUG: Tag '{tag_name}' not found, creating new tag...")
        print(f"Creating new tag '{tag_name}'...")
        new_tag = client.add_tag(name=tag_name, color=tag_color)
        if new_tag:
            tag_id = new_tag.get('id')
            print(f"✓ Created tag '{tag_name}' with ID: {tag_id}")
            return tag_id
        
        print(f"DEBUG: add_tag() returned None")
        return None
    except Exception as e:
        print(f"✗ Error managing tags: {e}", file=sys.stderr)
        return None


def update_monitor_tags(client: UptimeKumaClient, monitor_id: int, monitor_name: str, version: str, tag_prefix: str = 'version') -> bool:
    """Update monitor with version tag."""
    try:
        print(f"DEBUG: update_monitor_tags() called for monitor '{monitor_name}' (ID: {monitor_id}), version: {version}")
        
        # Get monitor list to find the monitor
        print(f"DEBUG: Getting monitor list to retrieve monitor details...")
        monitors = client.get_monitors()
        if monitors is None:
            print(f"DEBUG: get_monitors() returned None in update_monitor_tags")
            return False
        
        monitor = monitors.get(str(monitor_id))
        if not monitor:
            print(f"DEBUG: Monitor ID {monitor_id} not found in monitor list", file=sys.stderr)
            print(f"✗ Monitor ID {monitor_id} not found", file=sys.stderr)
            return False
        
        print(f"DEBUG: Found monitor details")
        
        # Get or create version tag
        version_tag_name = f'{tag_prefix}-{version}'
        print(f"DEBUG: Looking for/creating tag '{version_tag_name}'...")
        version_tag_id = get_or_create_tag(client, version_tag_name)
        if not version_tag_id:
            print(f"DEBUG: Failed to get or create tag '{version_tag_name}'")
            return False
        
        print(f"DEBUG: Using tag ID {version_tag_id} for '{version_tag_name}'")
        
        # Get current tags
        current_tags = monitor.get('tags', [])
        print(f"DEBUG: Monitor current tags: {current_tags}")
        current_tag_ids = [tag.get('tag_id') if isinstance(tag, dict) else tag for tag in current_tags]
        print(f"DEBUG: Current tag IDs: {current_tag_ids}")
        
        # Get all tags to filter out old version tags
        print(f"DEBUG: Getting all tags to filter old version tags...")
        all_tags = client.get_tags()
        if all_tags is None:
            print(f"DEBUG: get_tags() returned None in update_monitor_tags")
            return False
        
        # Filter out old version tags (tags starting with tag_prefix)
        filtered_tag_ids = []
        for tag_id in current_tag_ids:
            tag_info = next((t for t in all_tags if t.get('id') == tag_id), None)
            if tag_info:
                tag_name = tag_info.get('name', '')
                if not tag_name.startswith(f'{tag_prefix}-'):
                    filtered_tag_ids.append(tag_id)
                    print(f"DEBUG: Keeping tag ID {tag_id} ('{tag_name}')")
                else:
                    print(f"DEBUG: Removing old version tag ID {tag_id} ('{tag_name}')")
        
        # Add new version tag
        filtered_tag_ids.append(version_tag_id)
        print(f"DEBUG: Final tag IDs to set: {filtered_tag_ids}")
        
        # Update monitor with new tags
        monitor_data = monitor.copy()
        monitor_data['tags'] = filtered_tag_ids
        
        print(f"DEBUG: Calling edit_monitor to update tags...")
        success = client.edit_monitor(monitor_data)
        if success:
            print(f"✓ Successfully updated monitor '{monitor_name}' with tag '{version_tag_name}'")
        else:
            print(f"DEBUG: edit_monitor returned False")
        
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
    print(f"DEBUG: Fetching version from endpoint...")
    version = get_version(version_endpoint)
    if not version:
        print(f"DEBUG: Failed to fetch version, returning False")
        return False
    
    print(f"   ✓ Fetched version: {version}")
    
    # Get monitor list and find monitor by name
    print(f"DEBUG: Requesting monitor list...")
    monitors = client.get_monitors()
    if monitors is None:
        print(f"DEBUG: get_monitors() returned None, marking service as failed")
        print(f"   ✗ Failed to retrieve monitor list from Uptime Kuma")
        return False
    
    print(f"DEBUG: Successfully retrieved {len(monitors)} monitors")
    print(f"DEBUG: Looking for monitor named '{monitor_name}'...")
    
    monitor_id = None
    for mid, monitor in monitors.items():
        monitor_name_in_list = monitor.get('name', '')
        print(f"DEBUG: Checking monitor ID {mid}: '{monitor_name_in_list}'")
        if monitor_name_in_list == monitor_name:
            monitor_id = int(mid)
            print(f"DEBUG: Match found! Monitor ID: {monitor_id}")
            break
    
    if not monitor_id:
        print(f"DEBUG: Monitor '{monitor_name}' not found in list")
        print(f"✗ Monitor '{monitor_name}' not found", file=sys.stderr)
        return False
    
    print(f"   ✓ Found monitor ID: {monitor_id}")
    
    # Update tags
    print(f"DEBUG: Updating monitor tags...")
    success = update_monitor_tags(client, monitor_id, monitor_name, version, tag_prefix)
    print(f"DEBUG: update_monitor_tags returned: {success}")
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
