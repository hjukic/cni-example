#!/usr/bin/env python3
"""
Script to dynamically update Uptime Kuma monitor tags with version from version.txt endpoints.

This script:
1. Fetches versions from multiple service endpoints
2. Updates Uptime Kuma monitors with version tags
3. Can be run as a CronJob in Kubernetes
4. Requires SERVICES_CONFIG environment variable with JSON array of services
"""

import os
import sys
import requests
import json
from typing import Optional, List, Dict

# Configuration from environment variables
UPTIME_KUMA_URL = os.getenv('UPTIME_KUMA_URL', 'http://uptime-kuma.uptime-kuma.svc.cluster.local:3001')
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


def get_monitor_id(api_token: str, monitor_name: str) -> Optional[int]:
    """Get monitor ID by name."""
    try:
        headers = {
            'Authorization': f'Bearer {api_token}',
            'Content-Type': 'application/json'
        }
        response = requests.get(
            f'{UPTIME_KUMA_URL}/api/monitors',
            headers=headers,
            timeout=10,
            verify=VERIFY_SSL
        )
        response.raise_for_status()
        
        # Check if response has content
        if not response.text:
            print(f"✗ Error fetching monitors: Empty response from API", file=sys.stderr)
            print(f"   Status code: {response.status_code}", file=sys.stderr)
            return None
        
        # Try to parse JSON
        try:
            monitors = response.json()
        except json.JSONDecodeError as e:
            print(f"✗ Error parsing monitors response: {e}", file=sys.stderr)
            print(f"   Status code: {response.status_code}", file=sys.stderr)
            print(f"   Response content (first 500 chars): {response.text[:500]}", file=sys.stderr)
            return None
        
        # Check if monitors is a list
        if not isinstance(monitors, list):
            print(f"✗ Error: Expected list of monitors, got {type(monitors)}", file=sys.stderr)
            print(f"   Response: {response.text[:500]}", file=sys.stderr)
            return None
        
        for monitor in monitors:
            if monitor.get('name') == monitor_name:
                monitor_id = monitor.get('id')
                return monitor_id
        
        print(f"✗ Monitor '{monitor_name}' not found", file=sys.stderr)
        return None
    except requests.exceptions.RequestException as e:
        print(f"✗ Error fetching monitors: {e}", file=sys.stderr)
        if hasattr(e, 'response') and e.response is not None:
            print(f"   Status code: {e.response.status_code}", file=sys.stderr)
            print(f"   Response: {e.response.text[:500]}", file=sys.stderr)
        return None


def get_or_create_tag(api_token: str, tag_name: str) -> Optional[int]:
    """Get or create a tag and return its ID."""
    try:
        headers = {
            'Authorization': f'Bearer {api_token}',
            'Content-Type': 'application/json'
        }
        
        # Get all tags
        response = requests.get(
            f'{UPTIME_KUMA_URL}/api/tags',
            headers=headers,
            timeout=10,
            verify=VERIFY_SSL
        )
        response.raise_for_status()
        
        # Check if response has content
        if not response.text:
            print(f"✗ Error fetching tags: Empty response from API", file=sys.stderr)
            return None
        
        try:
            tags = response.json()
        except json.JSONDecodeError as e:
            print(f"✗ Error parsing tags response: {e}", file=sys.stderr)
            print(f"   Response: {response.text[:500]}", file=sys.stderr)
            return None
        
        # Check if tag exists
        for tag in tags:
            if tag.get('name') == tag_name:
                tag_id = tag.get('id')
                print(f"✓ Found existing tag '{tag_name}' with ID: {tag_id}")
                return tag_id
        
        # Create new tag
        print(f"Creating new tag '{tag_name}'...")
        create_response = requests.post(
            f'{UPTIME_KUMA_URL}/api/tags',
            headers=headers,
            json={'name': tag_name, 'color': '#3b82f6'},  # Blue color
            timeout=10,
            verify=VERIFY_SSL
        )
        create_response.raise_for_status()
        new_tag = create_response.json()
        tag_id = new_tag.get('id')
        print(f"✓ Created tag '{tag_name}' with ID: {tag_id}")
        return tag_id
        
    except requests.exceptions.RequestException as e:
        print(f"✗ Error managing tags: {e}", file=sys.stderr)
        return None


def update_monitor_tags(api_token: str, monitor_id: int, monitor_name: str, version: str, tag_prefix: str = 'version'):
    """Update monitor with version tag."""
    try:
        headers = {
            'Authorization': f'Bearer {api_token}',
            'Content-Type': 'application/json'
        }
        
        # Get current monitor details
        response = requests.get(
            f'{UPTIME_KUMA_URL}/api/monitor/{monitor_id}',
            headers=headers,
            timeout=10,
            verify=VERIFY_SSL
        )
        response.raise_for_status()
        monitor = response.json()
        
        # Get or create version tag
        version_tag_name = f'{tag_prefix}-{version}'
        version_tag_id = get_or_create_tag(api_token, version_tag_name)
        if not version_tag_id:
            return False
        
        # Get current tags
        current_tags = monitor.get('tags', [])
        current_tag_ids = [tag.get('tag_id') if isinstance(tag, dict) else tag for tag in current_tags]
        
        # Remove old version tags (tags starting with tag_prefix)
        if current_tags:
            all_tags_response = requests.get(
                f'{UPTIME_KUMA_URL}/api/tags',
                headers=headers,
                timeout=10,
                verify=VERIFY_SSL
            )
            all_tags_response.raise_for_status()
            all_tags = all_tags_response.json()
            
            # Filter out old version tags
            filtered_tag_ids = []
            for tag_id in current_tag_ids:
                tag_info = next((t for t in all_tags if t.get('id') == tag_id), None)
                if tag_info and not tag_info.get('name', '').startswith(f'{tag_prefix}-'):
                    filtered_tag_ids.append(tag_id)
            
            # Add new version tag
            filtered_tag_ids.append(version_tag_id)
        else:
            filtered_tag_ids = [version_tag_id]
        
        # Update monitor with new tags
        update_data = monitor.copy()
        update_data['tags'] = filtered_tag_ids
        
        update_response = requests.put(
            f'{UPTIME_KUMA_URL}/api/monitor/{monitor_id}',
            headers=headers,
            json=update_data,
            timeout=10,
            verify=VERIFY_SSL
        )
        update_response.raise_for_status()
        
        print(f"✓ Successfully updated monitor '{monitor_name}' with tag '{version_tag_name}'")
        return True
        
    except requests.exceptions.RequestException as e:
        print(f"✗ Error updating monitor '{monitor_name}': {e}", file=sys.stderr)
        return False


def process_service(api_token: str, service_config: Dict[str, str]) -> bool:
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
    
    # Get monitor ID
    monitor_id = get_monitor_id(api_token, monitor_name)
    if not monitor_id:
        return False
    
    print(f"   ✓ Found monitor ID: {monitor_id}")
    
    # Update tags
    success = update_monitor_tags(api_token, monitor_id, monitor_name, version, tag_prefix)
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
    if not UPTIME_KUMA_API_TOKEN:
        print("✗ Error: UPTIME_KUMA_API_TOKEN environment variable is required", file=sys.stderr)
        sys.exit(1)
    
    # Parse service configurations
    services = parse_services_config()
    if not services:
        sys.exit(1)
    
    print(f"\n🚀 Starting version sync for {len(services)} service(s)")
    print(f"   Uptime Kuma URL: {UPTIME_KUMA_URL}\n")
    
    # Process each service
    results = []
    for service_config in services:
        success = process_service(UPTIME_KUMA_API_TOKEN, service_config)
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


if __name__ == '__main__':
    main()

