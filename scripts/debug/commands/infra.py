"""Infrastructure analysis command - RAM tier stats, failure rates, etc."""

from datetime import datetime, timezone, timedelta


def run(client, options: dict):
    """Handle 'debug.py infra' command."""
    try:
        days = options.get('days', 3)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        
        # Get all workers from the time period
        result = client.db.supabase.table('workers').select(
            'id,status,created_at,last_heartbeat,metadata'
        ).gte('created_at', cutoff).execute()
        
        workers = result.data or []
        
        print("=" * 80)
        print(f"🖥️  INFRASTRUCTURE ANALYSIS (last {days} days)")
        print("=" * 80)
        print(f"\nTotal workers analyzed: {len(workers)}")
        
        # RAM tier analysis
        ram_stats = {}
        storage_stats = {}
        
        for w in workers:
            meta = w.get('metadata', {}) or {}
            ram = meta.get('ram_tier')
            storage = meta.get('storage_volume', 'Unknown')
            error_reason = meta.get('error_reason', '')
            
            # RAM tier stats
            if ram:
                if ram not in ram_stats:
                    ram_stats[ram] = {'total': 0, 'failed': 0, 'failure_reasons': {}}
                
                ram_stats[ram]['total'] += 1
                
                # Count heartbeat/stuck failures (the problematic ones)
                if w['status'] in ['error', 'terminated']:
                    if 'heartbeat' in error_reason.lower() or 'stuck' in error_reason.lower():
                        ram_stats[ram]['failed'] += 1
                        reason_key = error_reason[:50] if error_reason else 'Unknown'
                        ram_stats[ram]['failure_reasons'][reason_key] = \
                            ram_stats[ram]['failure_reasons'].get(reason_key, 0) + 1
            
            # Storage stats
            if storage not in storage_stats:
                storage_stats[storage] = {'total': 0, 'failed': 0}
            storage_stats[storage]['total'] += 1
            if w['status'] in ['error', 'terminated'] and error_reason:
                if 'heartbeat' in error_reason.lower() or 'stuck' in error_reason.lower():
                    storage_stats[storage]['failed'] += 1
        
        # Print RAM tier analysis
        print("\n" + "-" * 80)
        print("📊 FAILURE RATE BY RAM TIER")
        print("-" * 80)
        print(f"{'RAM Tier':<12} {'Workers':<10} {'Failures':<10} {'Fail Rate':<12} {'Status'}")
        print("-" * 80)
        
        for ram in sorted(ram_stats.keys(), reverse=True):
            stats = ram_stats[ram]
            fail_rate = (stats['failed'] / stats['total'] * 100) if stats['total'] > 0 else 0
            
            # Status indicator
            if fail_rate < 5:
                status = "✅ Good"
            elif fail_rate < 15:
                status = "⚠️  Warning"
            else:
                status = "❌ High failure"
            
            print(f"{ram}GB{'':<8} {stats['total']:<10} {stats['failed']:<10} {fail_rate:>6.1f}%{'':<5} {status}")
        
        # Show top failure reasons per tier
        print("\n" + "-" * 80)
        print("🔍 TOP FAILURE REASONS BY RAM TIER")
        print("-" * 80)
        
        for ram in sorted(ram_stats.keys(), reverse=True):
            stats = ram_stats[ram]
            if stats['failure_reasons']:
                print(f"\n{ram}GB RAM:")
                sorted_reasons = sorted(stats['failure_reasons'].items(), key=lambda x: -x[1])
                for reason, count in sorted_reasons[:3]:
                    print(f"  {count}x {reason}")
        
        # Print storage analysis
        print("\n" + "-" * 80)
        print("📍 FAILURE RATE BY STORAGE VOLUME")
        print("-" * 80)
        print(f"{'Storage':<15} {'Workers':<10} {'Failures':<10} {'Fail Rate'}")
        print("-" * 80)
        
        for storage in sorted(storage_stats.keys()):
            stats = storage_stats[storage]
            fail_rate = (stats['failed'] / stats['total'] * 100) if stats['total'] > 0 else 0
            print(f"{storage:<15} {stats['total']:<10} {stats['failed']:<10} {fail_rate:>6.1f}%")
        
        # Recommendations
        print("\n" + "-" * 80)
        print("💡 RECOMMENDATIONS")
        print("-" * 80)
        
        # Find best and worst RAM tiers
        if ram_stats:
            best_ram = min(ram_stats.keys(), key=lambda r: 
                (ram_stats[r]['failed'] / ram_stats[r]['total']) if ram_stats[r]['total'] > 0 else 0)
            worst_ram = max(ram_stats.keys(), key=lambda r: 
                (ram_stats[r]['failed'] / ram_stats[r]['total']) if ram_stats[r]['total'] > 5 else 0)
            
            best_rate = (ram_stats[best_ram]['failed'] / ram_stats[best_ram]['total'] * 100) \
                if ram_stats[best_ram]['total'] > 0 else 0
            worst_rate = (ram_stats[worst_ram]['failed'] / ram_stats[worst_ram]['total'] * 100) \
                if ram_stats[worst_ram]['total'] > 0 else 0
            
            if worst_rate > best_rate * 2 and ram_stats[worst_ram]['total'] > 5:
                print(f"• Consider deprioritizing {worst_ram}GB machines ({worst_rate:.1f}% failure rate)")
                print(f"  vs {best_ram}GB machines ({best_rate:.1f}% failure rate)")
            else:
                print("• RAM tier failure rates are relatively balanced")
        
        print("\n" + "=" * 80)
        
    except Exception as e:
        print(f"❌ Error analyzing infrastructure: {e}")
        import traceback
        if options.get('debug'):
            traceback.print_exc()


