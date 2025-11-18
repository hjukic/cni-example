#!/usr/bin/env python3
"""
Script to dynamically update Uptime Kuma monitor tags with version from version.txt endpoints.

This script uses the official uptime-kuma-api library to communicate with Uptime Kuma.
See: https://uptime-kuma-api.readthedocs.io/en/latest/

Usage:
  - Fetches versions from service endpoints
  - Creates/updates version tags in Uptime Kuma
  - Automatically removes old version tags
  - Can be run as a CronJob in Kubernetes
"""

import os
import sys
import json
import time
import traceback
import requests
from typing import Optional, List, Dict, Any
from uptime_kuma_api import UptimeKumaApi

# Configuration from environment variables
UPTIME_KUMA_URL = os.getenv('UPTIME_KUMA_URL', 'http://uptime-kuma.uptime-kuma.svc.cluster.local:3001')
UPTIME_KUMA_USERNAME = os.getenv('UPTIME_KUMA_USERNAME', '')
UPTIME_KUMA_PASSWORD = os.getenv('UPTIME_KUMA_PASSWORD', '')
VERIFY_SSL = os.getenv('VERIFY_SSL', 'false').lower() == 'true'

# Services configuration (JSON format)
SERVICES_CONFIG = os.getenv('SERVICES_CONFIG', '')


def get_version(version_endpoint: str, session: requests.Session) -> Optional[str]:
    """Fetch version from the version endpoint using a shared session."""
    try:
        response = session.get(version_endpoint, timeout=10, verify=VERIFY_SSL)
        response.raise_for_status()
        version = response.text.strip()
        return version
    except requests.exceptions.RequestException as e:
        print(f"✗ Error fetching version from {version_endpoint}: {e}", file=sys.stderr)
        return None


def connect_to_uptime_kuma(url: str, username: str, password: str) -> Optional[UptimeKumaApi]:
    """Connect and authenticate with Uptime Kuma."""
    try:
        print(f"Connecting to Uptime Kuma at {url}...")
        api = UptimeKumaApi(url)
        api.login(username, password)
        print("✓ Connected and authenticated successfully")
        return api
    except Exception as e:
        print(f"✗ Error connecting: {e}", file=sys.stderr)
        traceback.print_exc()
        return None


class TagCache:
    """Cache tag lookups to avoid repeated API calls."""

    def __init__(self, api: UptimeKumaApi):
        self.api = api
        tags = api.get_tags()
        self._tags_by_name: Dict[str, Dict[str, Any]] = {tag['name']: tag for tag in tags}
        self._tag_names_by_id: Dict[int, str] = {tag['id']: tag['name'] for tag in tags}

    def get_or_create(self, tag_name: str, tag_color: str = '#3b82f6') -> Optional[Dict[str, Any]]:
        if tag_name in self._tags_by_name:
            tag = self._tags_by_name[tag_name]
            print(f"✓ Found existing tag '{tag_name}' (ID: {tag['id']})")
            return tag

        try:
            print(f"Creating new tag '{tag_name}'...")
            new_tag = self.api.add_tag(name=tag_name, color=tag_color)
            print(f"✓ Created tag '{tag_name}' (ID: {new_tag['id']})")
            self._tags_by_name[tag_name] = new_tag
            self._tag_names_by_id[new_tag['id']] = tag_name
            return new_tag
        except Exception as e:
            print(f"✗ Error managing tags: {e}", file=sys.stderr)
            traceback.print_exc()
            return None

    def get_name(self, tag_id: Optional[int]) -> str:
        if tag_id is None:
            return ''
        return self._tag_names_by_id.get(tag_id, '')


def _extract_tag_id(tag: Any) -> Optional[int]:
    """Extract tag ID from various tag formats."""
    if isinstance(tag, dict):
        return tag.get('tag_id') or tag.get('id')
    return tag


def update_monitor_tags(
    api: UptimeKumaApi,
    monitor: Dict[str, Any],
    monitor_name: str,
    version: str,
    tag_cache: TagCache,
    tag_prefix: str = 'version',
) -> bool:
    """Update monitor with version tag."""
    try:
        version_tag_name = f'{tag_prefix}-{version}'
        version_tag = tag_cache.get_or_create(version_tag_name)
        
        if not version_tag:
            return False
        
        version_tag_id = version_tag['id']
        print(f"   Using tag ID: {version_tag_id}")
        
        # Find and remove old version tags
        current_tags = monitor.get('tags', [])
        updated_tags = []

        for tag in current_tags:
            tag_id = _extract_tag_id(tag)
            tag_name = tag.get('name') if isinstance(tag, dict) else tag_cache.get_name(tag_id)
            
            # Remove old version tags (but not the one we're adding)
            if tag_name.startswith(f'{tag_prefix}-') and tag_id != version_tag_id:
                print(f"   Removing old tag '{tag_name}'...")
                try:
                    api.delete_monitor_tag(tag_id=tag_id, monitor_id=monitor['id'])
                except Exception as e:
                    print(f"   ⚠ Warning: Could not remove old tag: {e}")
                continue

            updated_tags.append(tag)

        # Add the new version tag
        print(f"   Adding tag '{version_tag_name}'...")
        api.add_monitor_tag(tag_id=version_tag_id, monitor_id=monitor['id'], value='')

        # Track the new state locally so repeated runs avoid stale data
        updated_tags.append({'id': version_tag_id, 'name': version_tag_name})
        monitor['tags'] = updated_tags

        print(f"✓ Successfully updated monitor '{monitor_name}' with tag '{version_tag_name}'")
        return True
        
    except Exception as e:
        print(f"✗ Error updating monitor '{monitor_name}': {e}", file=sys.stderr)
        traceback.print_exc()
        return False


def process_service(
    api: UptimeKumaApi,
    session: requests.Session,
    monitor_map: Dict[str, Dict[str, Any]],
    tag_cache: TagCache,
    service_config: Dict[str, str],
) -> bool:
    """Process a single service configuration."""
    monitor_name = service_config.get('monitorName', '')
    version_endpoint = service_config.get('versionEndpoint', '')
    tag_prefix = service_config.get('tagPrefix', 'version')
    
    if not monitor_name or not version_endpoint:
        print(f"✗ Invalid service config: missing monitorName or versionEndpoint", file=sys.stderr)
        return False
    
    print(f"\n📦 Processing service: {monitor_name}")
    
    # Fetch version from endpoint
    version = get_version(version_endpoint, session)
    if not version:
        return False
    print(f"   ✓ Fetched version: {version}")
    
    # Find monitor by name
    monitor = monitor_map.get(monitor_name)
    if not monitor:
        print(f"   ✗ Monitor '{monitor_name}' not found", file=sys.stderr)
        return False
    
    # Update monitor with version tag
    return update_monitor_tags(api, monitor, monitor_name, version, tag_cache, tag_prefix)


def build_monitor_map(api: UptimeKumaApi) -> Dict[str, Dict[str, Any]]:
    """Return a dictionary of monitors keyed by name."""
    monitors = api.get_monitors()
    print(f"✓ Loaded {len(monitors)} monitor(s) from Uptime Kuma")
    return {monitor['name']: monitor for monitor in monitors}


def parse_services_config() -> List[Dict[str, str]]:
    """Parse services configuration from JSON environment variable."""
    if not SERVICES_CONFIG:
        print("✗ Error: SERVICES_CONFIG environment variable is required", file=sys.stderr)
        return []
    
    try:
        services = json.loads(SERVICES_CONFIG)
        if not isinstance(services, list) or not services:
            print("✗ Error: SERVICES_CONFIG must be a non-empty JSON array", file=sys.stderr)
            return []
        
        print(f"✓ Loaded {len(services)} service(s) from configuration")
        return services
    except json.JSONDecodeError as e:
        print(f"✗ Error parsing SERVICES_CONFIG: {e}", file=sys.stderr)
        return []


def main():
    """Main execution."""
    # Validate credentials
    if not UPTIME_KUMA_PASSWORD:
        print("✗ Error: UPTIME_KUMA_PASSWORD must be set", file=sys.stderr)
        sys.exit(1)
    
    # Parse service configurations
    services = parse_services_config()
    if not services:
        sys.exit(1)
    
    print(f"\n🚀 Starting version sync for {len(services)} service(s)")
    print(f"   Uptime Kuma URL: {UPTIME_KUMA_URL}\n")
    
    # Connect to Uptime Kuma
    api = connect_to_uptime_kuma(UPTIME_KUMA_URL, UPTIME_KUMA_USERNAME, UPTIME_KUMA_PASSWORD)
    if not api:
        sys.exit(1)
    
    session = requests.Session()
    try:
        monitor_map = build_monitor_map(api)
        tag_cache = TagCache(api)
        # Process each service
        results = [
            process_service(api, session, monitor_map, tag_cache, service)
            for service in services
        ]
        
        # Print summary
        successful = sum(results)
        failed = len(results) - successful
        
        print(f"\n📊 Summary:")
        print(f"   ✓ Successful: {successful}")
        if failed > 0:
            print(f"   ✗ Failed: {failed}")
            sys.exit(1)
        
        print("\n✓ All version tags updated successfully")
        
    finally:
        session.close()
        try:
            api.disconnect()
            print("Disconnected from Uptime Kuma")
        except:
            pass


if __name__ == '__main__':
    main()
