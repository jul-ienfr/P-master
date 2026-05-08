import math
from collections import Counter
from typing import Iterable, Optional, Sequence, TypeVar


T = TypeVar("T")


def center_from_bbox(bbox: tuple[int, int, int, int]) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def derive_legal_actions(action_button_names: Iterable[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    action_buttons: list[str] = []
    legal_actions: list[str] = []
    has_check = False
    has_call = False
    has_bet = False
    has_raise = False

    for button_name in action_button_names:
        class_name = str(button_name or "").lower()
        action_buttons.append(class_name)
        if class_name == "fold_button":
            legal_actions.append("FOLD")
        elif class_name in {"resume_hand", "im_back", "fast_fold_button"}:
            continue
        elif class_name == "check_button":
            has_check = True
        elif class_name in {"call_button", "all_in_call_button"}:
            has_call = True
        elif class_name == "bet_button":
            has_bet = True
        elif class_name == "raise_button":
            has_raise = True

    if has_check:
        legal_actions.append("CHECK")
    if has_call:
        legal_actions.append("CALL")
    if has_raise:
        legal_actions.append("RAISE")
    elif has_bet:
        legal_actions.append("BET")

    return tuple(dict.fromkeys(legal_actions)), tuple(dict.fromkeys(action_buttons))


def stable_window_value(
    history: Sequence[T],
    incoming: T,
    *,
    ignore_values: Sequence[T] = (),
) -> T:
    ignored = set(ignore_values)
    window = [value for value in [*history, incoming] if value not in ignored]
    if not window:
        return incoming

    counts = Counter(window)
    best_count = max(counts.values())
    if counts.get(incoming, 0) == best_count:
        return incoming

    for value in reversed(window):
        if counts[value] == best_count:
            return value

    return incoming


def smooth_state_confidence_window(
    history: Sequence[float],
    incoming_confidence: float,
    *,
    decay_floor: float = 0.75,
    average_floor: float = 0.65,
) -> float:
    incoming = max(0.0, min(float(incoming_confidence or 0.0), 1.0))
    if not history:
        return round(incoming, 3)

    recent = [max(0.0, min(float(value or 0.0), 1.0)) for value in history]
    previous = recent[-1]
    if incoming >= previous:
        return round(incoming, 3)

    recent_average = sum(recent) / len(recent)
    damped = max(incoming, previous * decay_floor, recent_average * average_floor)
    return round(min(damped, 1.0), 3)


def normalize_board_for_street(board: Sequence[str], street: str) -> tuple[str, ...]:
    expected_count = {
        "IDLE": 0,
        "PREFLOP": 0,
        "FLOP": 3,
        "TURN": 4,
        "RIVER": 5,
    }.get(street)
    if expected_count is None:
        return tuple(board)
    return tuple(board[:expected_count])


def derive_street(board: Sequence[str], hero_cards: Sequence[str]) -> str:
    if len(board) >= 5:
        return "RIVER"
    if len(board) == 4:
        return "TURN"
    if len(board) == 3:
        return "FLOP"
    if len(hero_cards) == 2:
        return "PREFLOP"
    return "IDLE"


def ordered_stacks_by_table_geometry(
    stack_bboxes: Sequence[tuple[int, int, int, int]],
    frame_shape: tuple[int, int],
    pot_bbox: Optional[tuple[int, int, int, int]] = None,
) -> list[tuple[str, tuple[int, int, int, int]]]:
    if not stack_bboxes:
        return []

    frame_h, frame_w = frame_shape
    center_x = frame_w / 2.0
    center_y = frame_h / 2.0
    
    # We use a slight static offset because the pot isn't perfectly the center of the seat ellipse
    if pot_bbox is not None:
        center_x, center_y = center_from_bbox(pot_bbox)
        center_y -= frame_h * 0.05 # L'ellipse des joueurs est souvent un peu plus haute

    # Elliptical projection mapping rather than raw polar
    # Tables are generally wider than they are tall
    rx = frame_w * 0.4
    ry = frame_h * 0.3

    angular_entries: list[tuple[float, float, tuple[int, int, int, int]]] = []
    for stack_bbox in stack_bboxes:
        sx, sy = center_from_bbox(stack_bbox)
        
        # Normalize coordinates relative to our ellipse anchor
        dx = (sx - center_x) / rx
        dy = (sy - center_y) / ry
        
        angle = (math.atan2(dy, dx) + 2.5 * math.pi) % (2.0 * math.pi)
        distance = math.hypot(dx, dy)
        angular_entries.append((angle, distance, stack_bbox))

    angular_entries.sort(key=lambda item: (item[0], item[1]))
    return [(f"seat_{index}", stack_bbox) for index, (_, _, stack_bbox) in enumerate(angular_entries)]


def infer_hero_seat_id(
    ordered_stacks: Sequence[tuple[str, tuple[int, int, int, int]]],
    hero_card_bboxes: Sequence[tuple[int, int, int, int]],
    frame_shape: tuple[int, int],
    last_hero_seat_id: Optional[str] = None,
) -> Optional[str]:
    if not ordered_stacks:
        return None

    frame_h, frame_w = frame_shape
    available_seat_ids = {seat_id for seat_id, _ in ordered_stacks}
    if not hero_card_bboxes:
        return last_hero_seat_id if last_hero_seat_id in available_seat_ids else None

    # Ellipse parameters for hero tracking relative to overall screen
    center_x = frame_w / 2.0
    center_y = frame_h / 2.0
    rx = frame_w * 0.4
    ry = frame_h * 0.3

    hero_centers = [center_from_bbox(card_bbox) for card_bbox in hero_card_bboxes]
    hx = sum(center[0] for center in hero_centers) / len(hero_centers)
    hy = sum(center[1] for center in hero_centers) / len(hero_centers)

    candidates: list[tuple[float, str]] = []
    for seat_id, stack_bbox in ordered_stacks:
        sx, sy = center_from_bbox(stack_bbox)
        
        # We calculate euclidean distance in normalized ellipse space rather than raw pixels
        # This makes it resilient to window stretching!
        dx = (sx - hx) / rx
        dy = (sy - hy) / ry
        score = math.hypot(dx, dy)

        candidates.append((score, seat_id))

    candidates.sort(key=lambda item: item[0])
    best_score, best_seat_id = candidates[0]

    # ... keep the rest of the switch logic

    candidates.sort(key=lambda item: item[0])
    best_score, best_seat_id = candidates[0]

    if last_hero_seat_id in available_seat_ids:
        prior_score = None
        prior_rank = None
        for idx, (score, seat_id) in enumerate(candidates):
            if seat_id == last_hero_seat_id:
                prior_score = score
                prior_rank = idx
                break

        # Keep the previously inferred hero seat when it stays competitive.
        if prior_rank is not None and prior_score is not None:
            seat_switch_tolerance = max(frame_w, frame_h) * 0.08
            if prior_rank <= 1 or prior_score <= best_score + seat_switch_tolerance:
                return last_hero_seat_id

    return best_seat_id
