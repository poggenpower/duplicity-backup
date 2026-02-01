import time

class TimeTracker:
    def __init__(self):
        # Stack stores tuples: (start_time, optional_id)
        self._active_starts = {}
        # Records store dicts: {'duration': float, 'id': str|None}
        self._records = {}

    def start(self, name: str, identifier: str | None = None):
        """Starts a timer with an optional specific ID for this instance."""
        if name not in self._active_starts:
            self._active_starts[name] = []
        self._active_starts[name].append((time.perf_counter(), identifier))

    def stop(self, name: str) -> float:
        """Stops the most recent timer for 'name'."""
        if name not in self._active_starts or not self._active_starts[name]:
            raise KeyError(f"Timer '{name}' was never started or already stopped.")
        
        start_time, identifier = self._active_starts[name].pop()
        elapsed = time.perf_counter() - start_time
        
        if name not in self._records:
            self._records[name] = []
        
        self._records[name].append({"duration": elapsed, "id": identifier, "is_running": False})
        return elapsed

    def report(self) -> dict:
        """Returns records. Running tasks are included and flagged."""
        now = time.perf_counter()
        report_data = {}
        
        all_names = set(self._records.keys()) | set(self._active_starts.keys())

        for name in all_names:
            # 1. Start with finished records
            records = list(self._records.get(name, []))
            
            # 2. Add snapshots of currently active timers
            active_list = self._active_starts.get(name, [])
            for start_time, identifier in active_list:
                records.append({
                    "duration": now - start_time,
                    "id": identifier,
                    "is_running": True
                })
            
            # 3. Aggregate stats
            if records:
                durations = [r["duration"] for r in records]
                total_time = sum(durations)
                
                report_data[name] = {
                    "total_time": total_time,
                    "count": len(records),
                    "average": total_time / len(records),
                    "is_running": any(r["is_running"] for r in records),
                    "items": records
                }
                
        return report_data

if __name__ == "__main__":
    # --- Example Usage ---
    tracker = TimeTracker()

    # 1. Loop with individual IDs
    for i in range(3):
        tracker.start("process_item", identifier=f"item_{i}")
        time.sleep(0.01)
        tracker.stop("process_item")

    # 2. Recursion with ID tracking
    def factorial_timer(n):
        tracker.start("factorial", identifier=f"depth_{n}")
        time.sleep(0.01)
        if n > 1:
            factorial_timer(n - 1)
            tracker.stop("factorial")
        # Note: the n=1 call isn't stopped yet to demonstrate 'is_running'

    factorial_timer(3)

    # View the result
    import json
    print(json.dumps(tracker.report(), indent=4))