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
        
        @self.sio.on('connect_error')
        def on_connect_error(data):
            print(f"✗ Connection error: {data}", file=sys.stderr)
            self.response_queue.put({'error': str(data)})
        
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
            # Wait a bit for connection to stabilize
            time.sleep(0.5)
            
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
            
            def login_callback(response):
                nonlocal login_response_received, login_success, login_error
                login_response_received = True
                if response.get('ok'):
                    login_success = True
                else:
                    login_error = response.get('msg', 'Authentication failed')
            
            # Register callback for 'res' event specifically for login
            # Use a unique event name to avoid conflicts
            login_event_id = f'login_res_{int(time.time() * 1000)}'
            
            def login_res_handler(response):
                nonlocal login_response_received, login_success, login_error
                print(f"DEBUG: Received login response: {response}")
                login_response_received = True
                if response.get('ok'):
                    login_success = True
                else:
                    login_error = response.get('msg', 'Authentication failed')
            
            # Register handler for 'res' event
            self.sio.on('res', login_res_handler)
            
            # Send login event
            print(f"Attempting to authenticate as user: {username if username else '(empty)'}")
            print("DEBUG: Sending login event...")
            self.sio.emit('login', {
                'username': username,
                'password': password
            })
            
            # Wait for response with longer timeout
            timeout = 10
            start_time = time.time()
            while (time.time() - start_time) < timeout:
                if login_response_received:
                    break
                time.sleep(0.1)
            
            # Remove the callback
            try:
                self.sio.off('res', login_res_handler)
            except:
                pass  # Ignore if handler wasn't registered
            
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
            # Clear previous data
            with self.lock:
                if 'monitorList' in self.event_data:
                    del self.event_data['monitorList']
            
            # Request monitor list
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
            # Clear previous data
            with self.lock:
                if 'tagList' in self.event_data:
                    del self.event_data['tagList']
            
            # Request tag list
            self.sio.emit('tagList')
            
            # Wait for response
            timeout = 5
            start_time = time.time()
            while (time.time() - start_time) < timeout:
                with self.lock:
                    if 'tagList' in self.event_data:
                        return self.event_data['tagList']
                time.sleep(0.1)
            
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
            # Clear any previous responses
            while not self.response_queue.empty():
                self.response_queue.get()
            
            # Send addTag event
            self.sio.emit('addTag', {
                'name': name,
                'color': color
            })
            
            # Wait for response
            timeout = 5
            start_time = time.time()
            while (time.time() - start_time) < timeout:
                try:
                    response = self.response_queue.get(timeout=0.5)
                    if response.get('ok'):
                        return response.get('tag')
                    else:
                        error_msg = response.get('msg', 'Failed to create tag')
                        print(f"✗ Error creating tag: {error_msg}", file=sys.stderr)
                        return None
                except:
                    continue
            
            print("✗ Timeout creating tag", file=sys.stderr)
            return None
        except Exception as e:
            print(f"✗ Error creating tag: {e}", file=sys.stderr)
            return None
    
    def edit_monitor(self, monitor_data: Dict[str, Any]) -> bool:
        """Update a monitor."""
        if not self.authenticated:
            print("✗ Not authenticated", file=sys.stderr)
            return False
        
        try:
            # Clear any previous responses
            while not self.response_queue.empty():
                self.response_queue.get()
            
            # Send editMonitor event
            self.sio.emit('editMonitor', monitor_data)
            
            # Wait for response
            timeout = 5
            start_time = time.time()
            while (time.time() - start_time) < timeout:
                try:
                    response = self.response_queue.get(timeout=0.5)
                    if response.get('ok'):
                        return True
                    else:
                        error_msg = response.get('msg', 'Failed to update monitor')
                        print(f"✗ Error updating monitor: {error_msg}", file=sys.stderr)
                        return False
                except:
                    continue
            
            print("✗ Timeout updating monitor", file=sys.stderr)
            return False
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
            if tag.get('name') == tag_name:
                tag_id = tag.get('id')
                print(f"✓ Found existing tag '{tag_name}' with ID: {tag_id}")
                return tag_id
        
        # Create new tag
        print(f"Creating new tag '{tag_name}'...")
        new_tag = client.add_tag(name=tag_name, color=tag_color)
        if new_tag:
            tag_id = new_tag.get('id')
            print(f"✓ Created tag '{tag_name}' with ID: {tag_id}")
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
        
        # Get current tags
        current_tags = monitor.get('tags', [])
        current_tag_ids = [tag.get('tag_id') if isinstance(tag, dict) else tag for tag in current_tags]
        
        # Get all tags to filter out old version tags
        all_tags = client.get_tags()
        if all_tags is None:
            return False
        
        # Filter out old version tags (tags starting with tag_prefix)
        filtered_tag_ids = []
        for tag_id in current_tag_ids:
            tag_info = next((t for t in all_tags if t.get('id') == tag_id), None)
            if tag_info and not tag_info.get('name', '').startswith(f'{tag_prefix}-'):
                filtered_tag_ids.append(tag_id)
        
        # Add new version tag
        filtered_tag_ids.append(version_tag_id)
        
        # Update monitor with new tags
        monitor_data = monitor.copy()
        monitor_data['tags'] = filtered_tag_ids
        
        success = client.edit_monitor(monitor_data)
        if success:
            print(f"✓ Successfully updated monitor '{monitor_name}' with tag '{version_tag_name}'")
        
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
        return False
    
    monitor_id = None
    for mid, monitor in monitors.items():
        if monitor.get('name') == monitor_name:
            monitor_id = int(mid)
            break
    
    if not monitor_id:
        print(f"✗ Monitor '{monitor_name}' not found", file=sys.stderr)
        return False
    
    print(f"   ✓ Found monitor ID: {monitor_id}")
    
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
