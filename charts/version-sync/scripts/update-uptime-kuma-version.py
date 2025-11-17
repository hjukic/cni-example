#!/usr/bin/env python3
"""
Script to dynamically update Uptime Kuma monitor tags with version from version.txt endpoints.

This script uses the official uptime-kuma-api library to communicate with Uptime Kuma.
See: https://uptime-kuma-api.readthedocs.io/en/latest/

This script:
1. Fetches versions from multiple service endpoints
2. Connects to Uptime Kuma via the official API
3. Updates Uptime Kuma monitors with version tags using add_monitor_tag
4. Can be run as a CronJob in Kubernetes
5. Requires SERVICES_CONFIG environment variable with JSON array of services
"""

import os
import sys
import requests
import json
import time
from typing import Optional, List, Dict, Any
from uptime_kuma_api import UptimeKumaApi, MonitorType

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


def connect_to_uptime_kuma(url: str, username: str, password: str) -> Optional[UptimeKumaApi]:
    """Connect and authenticate with Uptime Kuma using the official API."""
    try:
        print(f"Connecting to Uptime Kuma at {url}...")
        api = UptimeKumaApi(url)
        
        # Login
        if username:
            print(f"Authenticating as user: {username}")
            api.login(username, password)
        else:
            print("Authenticating with password only...")
            api.login('', password)
        
        print("✓ Connected and authenticated successfully")
        return api
    except Exception as e:
        print(f"✗ Error connecting to Uptime Kuma: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return None


def get_or_create_tag(api: UptimeKumaApi, tag_name: str, tag_color: str = '#3b82f6') -> Optional[Dict[str, Any]]:
    """Get or create a tag and return the full tag object."""
    try:
        # Get all tags
        tags = api.get_tags()
        
        # Check if tag exists
        for tag in tags:
            if tag.get('name', '') == tag_name:
                print(f"✓ Found existing tag '{tag_name}' (ID: {tag.get('id')})")
                return tag
        
        # Create new tag
        print(f"Creating new tag '{tag_name}'...")
        new_tag = api.add_tag(name=tag_name, color=tag_color)
        print(f"✓ Created tag '{tag_name}' (ID: {new_tag.get('id')})")
        
        # Wait a moment for the tag to propagate
        time.sleep(0.5)
        
        return new_tag
    except Exception as e:
        print(f"✗ Error managing tags: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return None


def update_monitor_tags(api: UptimeKumaApi, monitor_id: int, monitor_name: str, version: str, tag_prefix: str = 'version') -> bool:
    """Update monitor with version tag using the official API's add_monitor_tag method."""
    try:
        # Get monitor details
        monitor = api.get_monitor(monitor_id)
        if not monitor:
            print(f"✗ Monitor ID {monitor_id} not found", file=sys.stderr)
            return False
        
        # Get or create version tag
        version_tag_name = f'{tag_prefix}-{version}'
        version_tag_obj = get_or_create_tag(api, version_tag_name)
        if not version_tag_obj:
            return False
        
        version_tag_id = version_tag_obj.get('id')
        if not version_tag_id:
            print(f"✗ Error: Created tag has no ID", file=sys.stderr)
            return False
        
        print(f"   Using tag ID: {version_tag_id} for tag '{version_tag_name}'")
        
        # Get current tags
        current_tags = monitor.get('tags', [])
        print(f"   Current monitor tags: {[tag.get('name', tag.get('tag_id', tag)) for tag in current_tags]}")
        
        # Get all available tags to map IDs to names
        all_tags = api.get_tags()
        tag_map = {tag['id']: tag for tag in all_tags}
        
        # Find and remove old version tags
        tags_to_remove = []
        for tag in current_tags:
            if isinstance(tag, dict):
                tag_id = tag.get('tag_id') or tag.get('id')
                tag_name = tag.get('name', '')
                if not tag_name and tag_id in tag_map:
                    tag_name = tag_map[tag_id].get('name', '')
            else:
                # Tag is just an ID
                tag_id = tag
                tag_name = tag_map.get(tag_id, {}).get('name', '')
            
            # If this is a version tag (starts with tag_prefix), mark for removal
            if tag_name and tag_name.startswith(f'{tag_prefix}-'):
                if tag_id != version_tag_id:  # Don't remove the tag we're about to add
                    tags_to_remove.append((tag_id, tag_name))
        
        # Remove old version tags
        for tag_id, tag_name in tags_to_remove:
            print(f"   Removing old tag '{tag_name}' (ID: {tag_id})...")
            try:
                api.delete_monitor_tag(tag_id=tag_id, monitor_id=monitor_id)
                print(f"   ✓ Removed old tag '{tag_name}'")
                time.sleep(0.2)  # Small delay between operations
            except Exception as e:
                print(f"   ⚠ Warning: Could not remove old tag: {e}")
        
        # Add the new version tag using the official add_monitor_tag method
        print(f"   Adding tag '{version_tag_name}' to monitor...")
        try:
            # This is the key method that should properly apply the tag to the monitor
            api.add_monitor_tag(
                tag_id=version_tag_id,
                monitor_id=monitor_id,
                value=''  # Empty value for simple tags
            )
            print(f"✓ Successfully added tag '{version_tag_name}' to monitor '{monitor_name}'")
            
            # Wait a moment for the change to propagate
            time.sleep(0.5)
            
            # Verify the tag was added
            updated_monitor = api.get_monitor(monitor_id)
            updated_tags = updated_monitor.get('tags', [])
            
            # Check if our tag is present
            tag_found = False
            for tag in updated_tags:
                if isinstance(tag, dict):
                    tag_id = tag.get('tag_id') or tag.get('id')
                    if tag_id == version_tag_id:
                        tag_found = True
                        break
            
            if tag_found:
                print(f"   ✓ Verified: Tag is now attached to the monitor")
            else:
                print(f"   ⚠ Warning: Tag added but not immediately visible in monitor (may need time to propagate)")
            
            return True
        except Exception as e:
            print(f"✗ Failed to add tag to monitor: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return False
        
    except Exception as e:
        print(f"✗ Error updating monitor '{monitor_name}': {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False


def process_service(api: UptimeKumaApi, service_config: Dict[str, str]) -> bool:
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
    monitors = api.get_monitors()
    
    monitor_id = None
    for monitor in monitors:
        if monitor.get('name', '') == monitor_name:
            monitor_id = monitor.get('id')
            break
    
    if not monitor_id:
        print(f"   ✗ Monitor '{monitor_name}' not found", file=sys.stderr)
        return False
    
    print(f"   ✓ Found monitor (ID: {monitor_id})")
    
    # Update tags
    success = update_monitor_tags(api, monitor_id, monitor_name, version, tag_prefix)
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
    
    # Connect to Uptime Kuma
    password = UPTIME_KUMA_API_TOKEN if UPTIME_KUMA_API_TOKEN else UPTIME_KUMA_PASSWORD
    username = UPTIME_KUMA_USERNAME if UPTIME_KUMA_USERNAME else ''
    
    api = connect_to_uptime_kuma(UPTIME_KUMA_URL, username, password)
    if not api:
        print("✗ Failed to connect to Uptime Kuma", file=sys.stderr)
        sys.exit(1)
    
    try:
        # Process each service
        results = []
        for service_config in services:
            success = process_service(api, service_config)
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
        try:
            api.disconnect()
            print("Disconnected from Uptime Kuma")
        except Exception as e:
            print(f"⚠ Warning: Error disconnecting: {e}", file=sys.stderr)


if __name__ == '__main__':
    main()
