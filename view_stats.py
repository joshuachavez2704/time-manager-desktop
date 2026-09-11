# view_stats.py
from src.database import TimeTrackerDB

def main():
    db = TimeTrackerDB()
    results = db.get_daily_summary()

    if not results:
        print("No activity recorded for today yet.")
        return

    print(f"\n{'Target':<30} | {'Type':<10} | {'Time Spent':<15}")
    print("-" * 60)

    for target_name, target_type, duration_seconds in results:
        hours, remainder = divmod(duration_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        formatted_time = f"{hours:02d}h {minutes:02d}m {seconds:02d}s"

        print(f"{target_name:<30} | {target_type:<10} | {formatted_time:<15}")

if __name__ == "__main__":
    main()
    