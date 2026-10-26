import threading

def _make_gc_overlap_observer(clock, *, max_events=64):
    events = []
    starts = []
    status = {"dropped": False, "unmatched": False, "clockfail": False}

    def observe(phase, info):
        try:
            generation = info.get("generation")
            if type(generation) is not int or phase not in {"start", "stop"}:
                status["unmatched"] = True
                return
            ident = threading.get_ident()
            try:
                wall_ns = clock.perf_counter_ns()
                cpu_ns = clock.thread_time_ns()
            except BaseException:
                wall_ns = cpu_ns = None
                status["clockfail"] = True
            if len(events) < max_events:
                events.append((phase, generation, ident, wall_ns, cpu_ns))
            else:
                status["dropped"] = True
            if phase == "start":
                if len(starts) < max_events:
                    starts.append((generation, ident))
                else:
                    status["dropped"] = True
            else:
                for index in range(len(starts) - 1, -1, -1):
                    if starts[index] == (generation, ident):
                        del starts[index]
                        break
                else:
                    status["unmatched"] = True
        except BaseException:
            status["clockfail"] = True

    return observe, events, starts, status

def _remove_exact_gc_observer(callbacks, observer):
    for index, callback in enumerate(callbacks):
        if callback is observer:
            del callbacks[index]
            return True
    return False
