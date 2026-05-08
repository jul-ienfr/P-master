# Poker Bot Reliability Implementation Plan

This plan details the strategy for addressing four critical areas of reliability in the live poker bot system, focusing on improving state fidelity, robust bounding, and timing tolerances across asynchronous tasks and vision processing.

## 1. Tracker & Concurrency (`src/bot/table_tracker.py`)
**Goal:** Add thread-safety limits and safe task wrappers for database state mutations triggered by OCR updates. 

*   **Actionable Strategy:**
    *   Initialize an `asyncio.Lock` instance in `TableTracker.__init__` to protect the concurrent-critical sections of the state machine.
    *   Apply this lock inside the main `update_from_vision` method to prevent race conditions where out-of-order frames might corrupt pot and stack histories concurrently.
    *   Create a safe wrapper method (e.g., `_safe_fire_db_task(coro)`) to wrap `asyncio.create_task` invocations involving database calls wrapper `self.db.*`. Inside the wrapper, wrap the passed coroutine in a `try...except` block that catches and logs any internal Exceptions, preventing unhandled exceptions from tearing down the application loop.
    *   Update existing calls to `asyncio.create_task` inside `update_from_vision`, `_record_action`, and `_save_hand_history` to use the wrapper.

## 2. OCR Logic & Bounds (`src/vision/ocr.py`)
**Goal:** Fix the "Phantom Bet" bug where OCR resets artificially inflate values, bounding OCR bounds by absolute stack size, and ensuring regex substitutions don't grab garbage.

*   **Actionable Strategy:**
    *   *Regex String Validation:* In `PokerOCR.parse_amount`, improve the preliminary candidate filter so strings like random "O0L" noise aren't parsed purely as number blobs. Inject strict boundary conditions in the `re.finditer` call and the subsequent stripping process.
    *   *Stack Bounding:* Modify the candidate scoring inside `parse_amount` logic (or an associated bounding layer in the sanity checker) so parsed value jumps are bounded reasonably based on the visual limits (e.g., ignoring parses over 1,000,000 BBs if we know the physical limit). While OCR operates statelessly, we can add a basic `max_value_boundary` check after `float()` casting to discard impossible phantom values.
    *   *Correction Validation*: Address the O/0, I/1 replacement logic inside `normalize_candidate`. Before returning, ensure the resulting matched pattern isn't solely derived from substitutions without original structural digits.
    
## 3. CPU & Timeout Resilience (`src/vision/capture.py` & OCR)
**Goal:** Add `await asyncio.sleep(1/fps)` checks to non-dxcam loops, and create timeout-fallback logic if temporal filtering gets blocked.

*   **Actionable Strategy:**
    *   *Pacing Non-DXcam Loops:* In systems where loops execute relying on `get_latest_frame()` without internal backpressure (specifically `window` or `imagegrab` capture loops calling it), explicitly document/prepare adding pacing loops (the actual loop invoking `get_latest_frame` is likely upstream from `capture.py`, but it should be noted that `capture.py` does not autonomously throttle `ImageGrab` if polled rapidly). 
    *   *Fallback timeout logic:* For temporal OCR (in `src/vision/temporal_ocr.py`, referenced implicitly), insert an awaitable `timeout` context. If the temporal filter takes more than a specific frame-length budget (e.g., >200ms) to resolve a fuzzy read into a crisp vote, fallback immediately to `FOLD` or the most conservative action to prevent the bot timing out its turn while thinking.
    
## 4. Hero Cards Safety (`src/vision/detector.py`)
**Goal:** Refine `TemplateFallbackDetector._detect_hero_cards` so tooltips occluding cards don't immediately clear the player's holding.

*   **Actionable Strategy:**
    *   *Frame History Spanning:* The `TableTracker` resets `self.hero_cards` to empty entirely based on `hero_cards = list(vision_state.get("hero_cards", []))` each frame. Instead of relying purely on the tracker to catch this via distinct hero rollover, we can buffer temporal state.
    *   *Vision Thresholds:* Inside `_detect_hero_cards` (or its helper `_detect_cards_from_search_area`), currently if fewer than 2 detections hit, it returns `[]` instantly. Instead, relax the strict "must return 2" constraint. Introduce a mechanism (or logic at the tracker level) to merge detections over a sliding frame window (e.g. `deque(maxlen=3)`). If one card is occluded but was seen in the last 2 frames, carry it over.

### Critical Files for Implementation
- c:\Users\julie\Desktop\Poker-master\src\bot\table_tracker.py
- c:\Users\julie\Desktop\Poker-master\src\vision\ocr.py
- c:\Users\julie\Desktop\Poker-master\src\vision\capture.py
- c:\Users\julie\Desktop\Poker-master\src\vision\detector.py
