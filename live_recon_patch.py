import re

with open("src/bot/live_reconstruction.py", "r", encoding="utf-8") as f:
    code = f.read()

new_ordered = """def ordered_stacks_by_table_geometry(
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
"""

new_infer = """def infer_hero_seat_id(
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
"""

code = re.sub(
    r'def ordered_stacks_by_table_geometry.*?return \[\(f"seat_\{index\}", stack_bbox\) for index, \(_, _, stack_bbox\) in enumerate\(angular_entries\)\]\n',
    new_ordered,
    code, flags=re.DOTALL
)

# Replace the infer_hero_seat_id until `candidates.sort`
code = re.sub(
    r'def infer_hero_seat_id\(.*?candidates\.append\(\(score, seat_id\)\)\n\n    candidates\.sort\(key=lambda item: item\[0\]\)',
    new_infer + '\n    candidates.sort(key=lambda item: item[0])',
    code, flags=re.DOTALL
)

with open("src/bot/live_reconstruction.py", "w", encoding="utf-8") as f:
    f.write(code)
