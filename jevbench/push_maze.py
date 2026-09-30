"""Deterministic, screenshot-only Sokoban and key/door maze tasks.

Authoring solvers are deliberately outside the actor tool surface.  Certificates
are recomputed from the board rather than trusted when :func:`certify` is called.
"""
from __future__ import annotations

from collections import deque
import copy
import hashlib
import heapq
import itertools
import json
import math
import random

from PIL import Image, ImageDraw, ImageFont

DIRECTIONS = (("up", 0, -1), ("down", 0, 1), ("left", -1, 0), ("right", 1, 0))
DELTA = {name: (dx, dy) for name, dx, dy in DIRECTIONS}


def _topology(data):
    floor = tuple(sorted(tuple(p) for p in data["floor"]))
    index = {p: i for i, p in enumerate(floor)}
    adjacency = tuple(tuple(index.get((x + dx, y + dy), -1)
                            for _, dx, dy in DIRECTIONS) for x, y in floor)
    return floor, index, adjacency


def _walk(player, boxes, adj):
    """Exact legal walking distances and predecessors with stationary boxes."""
    paths = {player: ()}
    queue = deque([player])
    while queue:
        here = queue.popleft()
        for direction, nxt in enumerate(adj[here]):
            if nxt >= 0 and nxt not in boxes and nxt not in paths:
                paths[nxt] = paths[here] + (direction,)
                queue.append(nxt)
    return paths


def _sokoban_solve(data, *, push_cost=False, lock_goals=False, state_limit=2_000_000):
    """Dijkstra over pushes with exact inter-push walks (complete state search).

    Walking-only suffixes cannot improve a Sokoban solution.  Thus contracting
    walks into exact shortest paths preserves minimum atomic-move distance.
    For push distance, zero-cost walks are contracted into reachable regions.
    """
    floor, index, adj = _topology(data)
    goals = frozenset(index[tuple(p)] for p in data["goals"])
    initial_boxes = frozenset(index[tuple(p)] for p in data["boxes"])
    player = index[tuple(data["player"])]
    initial = (player, initial_boxes)
    dead = _dead_squares(data)
    if push_cost:
        initial = (min(_walk(player, initial_boxes, adj)), initial_boxes)
    best = {initial: 0}
    parent = {}
    serial = itertools.count()
    queue = [(0, next(serial), initial)]
    explored = 0
    while queue:
        cost, _, state = heapq.heappop(queue)
        if best.get(state) != cost:
            continue
        explored += 1
        if explored > state_limit:
            raise RuntimeError("Sokoban exact-search state budget exhausted; no certificate")
        p, boxes = state
        if boxes == goals:
            actions = []
            cursor = state
            while cursor != initial:
                previous, moves = parent[cursor]
                actions.extend(reversed(moves))
                cursor = previous
            actions.reverse()
            return {"distance": cost, "path": actions, "states": explored}
        walks = _walk(p, boxes, adj)
        for box in sorted(boxes):
            if lock_goals and box in goals:
                continue
            for direction in range(4):
                standing = adj[box][direction ^ 1]
                destination = adj[box][direction]
                if standing not in walks or destination < 0 or destination in boxes or destination in dead:
                    continue
                moved = (boxes - {box}) | {destination}
                newp = box
                if push_cost:
                    newp = min(_walk(newp, moved, adj))
                nxt = (newp, moved)
                step = 1 if push_cost else len(walks[standing]) + 1
                newcost = cost + step
                if newcost < best.get(nxt, math.inf):
                    best[nxt] = newcost
                    parent[nxt] = (state, walks[standing] + (direction,))
                    heapq.heappush(queue, (newcost, next(serial), nxt))
    return {"distance": None, "path": [], "states": explored}


def _dead_squares(data):
    """Reverse-pull reachability ignoring other boxes; complement is unsolvable."""
    _, index, adj = _topology(data)
    reachable = {index[tuple(p)] for p in data["goals"]}
    queue = deque(reachable)
    while queue:
        box = queue.popleft()
        for direction in range(4):
            prior = adj[box][direction]
            stand = adj[prior][direction] if prior >= 0 else -1
            if stand >= 0 and prior not in reachable:
                reachable.add(prior)
                queue.append(prior)
    return set(range(len(adj))) - reachable


def _deadlock_witness(data):
    """Search reachable push states for a push to a proven dead square."""
    _, index, adj = _topology(data)
    dead = _dead_squares(data)
    goals = frozenset(index[tuple(p)] for p in data["goals"])
    boxes = frozenset(index[tuple(p)] for p in data["boxes"])
    initial = (index[tuple(data["player"])], boxes)
    queue = deque([(initial, ())])
    seen = set()
    while queue:
        (p, boxes), prefix = queue.popleft()
        if boxes == goals:
            # A winning state is terminal; no post-win move can be a witness.
            continue
        walks = _walk(p, boxes, adj)
        canonical = (min(walks), boxes)
        if canonical in seen:
            continue
        seen.add(canonical)
        for box in sorted(boxes):
            for direction in range(4):
                standing, dest = adj[box][direction ^ 1], adj[box][direction]
                if standing not in walks or dest < 0 or dest in boxes:
                    continue
                moves = prefix + walks[standing] + (direction,)
                if dest in dead:
                    return {"path": list(moves), "dead_square": list(sorted(index, key=index.get)[dest]),
                            "proof": "box cannot reach any goal even with all other boxes removed"}
                queue.append(((box, (boxes - {box}) | {dest}), moves))
    return None


def _maze_bfs(data):
    floor, index, adj = _topology(data)
    keys = {index[tuple(p)]: i for i, p in enumerate(data["keys"])}
    doors = {index[tuple(p)]: i for i, p in enumerate(data["doors"])}
    all_bits = (1 << len(keys)) - 1
    target = index[tuple(data["exit"])]
    initial = (index[tuple(data["player"])], 0, 0)
    queue, parent = deque([initial]), {initial: None}
    while queue:
        state = queue.popleft()
        p, held, opened = state
        if p == target and held == opened == all_bits:
            path = []
            while parent[state] is not None:
                state, direction = parent[state]
                path.append(direction)
            return {"distance": len(path), "path": list(reversed(path)), "states": len(parent)}
        for direction, nxt in enumerate(adj[p]):
            if nxt < 0 or (nxt in doors and not held & (1 << doors[nxt])):
                continue
            nk = held | (1 << keys[nxt] if nxt in keys else 0)
            nd = opened | (1 << doors[nxt] if nxt in doors else 0)
            candidate = (nxt, nk, nd)
            if candidate not in parent:
                parent[candidate] = (state, direction)
                queue.append(candidate)
    return {"distance": None, "path": [], "states": len(parent)}


def _component(floor, start, blocked=()):
    floor = set(floor) - set(blocked)
    reached, queue = {start}, deque([start])
    while queue:
        x, y = queue.popleft()
        for _, dx, dy in DIRECTIONS:
            p = (x + dx, y + dy)
            if p in floor and p not in reached:
                reached.add(p)
                queue.append(p)
    return reached


def _maze_structure(data):
    floor = set(map(tuple, data["floor"]))
    start, exit_cell = tuple(data["player"]), tuple(data["exit"])
    keys, doors = list(map(tuple, data["keys"])), list(map(tuple, data["doors"]))
    # Blocking door j while treating all others as open is a conservative,
    # graph-theoretic proof that key i depends on first opening door j.
    depends = []
    for i, key in enumerate(keys):
        deps = [j for j, door in enumerate(doors)
                if key not in _component(floor, start, [door])]
        if i in deps:
            raise ValueError("key is behind its own door")
        depends.append(deps)
    def depth(i, stack=()):
        if i in stack:
            raise ValueError("cyclic key dependency")
        return max((1 + depth(j, stack + (i,)) for j in depends[i]), default=0)
    chain = max(map(depth, range(len(keys))), default=0)
    # A distinct off-route connected component with a mandatory key separated
    # by a bridge must be entered and exited. Nested edges in one branch count
    # only once, so long corridors do not inflate the backtrack count.
    parent, queue = {start: None}, deque([start])
    while queue:
        p = queue.popleft()
        for _, dx, dy in DIRECTIONS:
            nxt = (p[0] + dx, p[1] + dy)
            if nxt in floor and nxt not in parent:
                parent[nxt] = p
                queue.append(nxt)
    if exit_cell not in parent:
        raise ValueError("exit disconnected")
    spine = set()
    cursor = exit_cell
    while cursor is not None:
        spine.add(cursor)
        cursor = parent[cursor]
    remaining = floor - spine
    branches = []
    while remaining:
        component = _component(remaining, min(remaining))
        remaining -= component
        boundary = [(p, (p[0] + dx, p[1] + dy)) for p in component
                    for _, dx, dy in DIRECTIONS if (p[0] + dx, p[1] + dy) in spine]
        contains = [i for i, key in enumerate(keys) if key in component]
        if len(boundary) == 1 and contains:
            branches.append({"bridge": [list(p) for p in boundary[0]], "keys": contains})
    return {"dependencies": depends, "dependency_depth": chain,
            "necessary_backtracks": len(branches), "key_branches": branches}


def _random_tree(size, rng):
    nodes = [(x, y) for y in range(1, size - 1, 2) for x in range(1, size - 1, 2)]
    edges = [(p, (p[0] + dx, p[1] + dy)) for p in nodes for dx, dy in ((2, 0), (0, 2))
             if (p[0] + dx, p[1] + dy) in nodes]
    rng.shuffle(edges)
    roots = {p: p for p in nodes}
    def find(p):
        while roots[p] != p:
            p = roots[p]
        return p
    floor = set(nodes)
    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            roots[ra] = rb
            floor.add(((a[0] + b[0]) // 2, (a[1] + b[1]) // 2))
    return floor


def _generate_maze(seed, tier):
    rng = random.Random(f"jev-key-maze-v1:{seed}:{tier}")
    count, size, lo, hi = (3, 9, 45, 64) if tier == "hard" else (4, 11, 65, 88)
    for attempt in range(10_000):
        floor = _random_tree(size, rng)
        neighbors = {p: [q for _, dx, dy in DIRECTIONS
                         if (q := (p[0] + dx, p[1] + dy)) in floor] for p in floor}
        leaves = [p for p in sorted(floor) if len(neighbors[p]) == 1]
        rng.shuffle(leaves)
        for start, end in itertools.permutations(leaves, 2):
            parent, queue = {start: None}, deque([start])
            while queue:
                p = queue.popleft()
                for q in neighbors[p]:
                    if q not in parent:
                        parent[q] = p
                        queue.append(q)
            spine, cursor = [], end
            while cursor is not None:
                spine.append(cursor)
                cursor = parent[cursor]
            spine.reverse()
            si = {p: i for i, p in enumerate(spine)}
            candidates = []
            for leaf in leaves:
                if leaf in si:
                    continue
                path, p = [], leaf
                while p not in si:
                    path.append(p)
                    p = parent[p]
                candidates.append((si[p], leaf, tuple(path)))
            for chosen in itertools.combinations(sorted(candidates), count - 1):
                positions = [row[0] for row in chosen]
                if len(set(positions)) != count - 1 or positions[-1] + 4 >= len(spine):
                    continue
                if any(b - a < 2 for a, b in zip(positions, positions[1:])):
                    continue
                distance = len(spine) - 1 + 2 * len(set().union(*(set(row[2]) for row in chosen)))
                if not lo <= distance <= hi:
                    continue
                keys = [row[1] for row in chosen] + [spine[positions[-1] + 2]]
                doors = [spine[p + 1] for p in positions] + [spine[positions[-1] + 3]]
                data = {"width": size, "height": size, "floor": list(map(list, sorted(floor))),
                        "player": list(start), "exit": list(end), "keys": list(map(list, keys)),
                        "doors": list(map(list, doors))}
                result = _maze_bfs(data)
                if result["distance"] != distance:
                    raise AssertionError("tree-tour distance and full state BFS disagree")
                record = {"family": "key_maze", "tier": tier, "seed": seed,
                          "goal": "Collect every key, open every matching door, and reach EXIT.",
                          "data": data, "certificate": {}, "reference_actions": _actions(result["path"])}
                record["certificate"] = certify(record)
                return record
    raise RuntimeError("No maze meets all structural and exact-distance gates within generation budget")


def _actions(path):
    return [{"tool": "press", "key": DIRECTIONS[d][0]} for d in path]


def _reverse_sokoban_states(data, limit=20_000):
    """BFS over legal reverse pushes, rooted in every solved player region."""
    floor, index, adj = _topology(data)
    boxes = frozenset(index[tuple(p)] for p in data["goals"])
    remaining = set(range(len(floor))) - boxes
    queue, seen = deque(), {}
    while remaining:
        region = _walk(min(remaining), boxes, adj)
        state = (min(region), boxes)
        remaining -= region.keys()
        seen[state] = 0
        queue.append(state)
    while queue and len(seen) < limit:
        player, boxes = queue.popleft()
        depth = seen[(player, boxes)]
        if depth >= 30:
            continue
        reachable = _walk(player, boxes, adj)
        for box in sorted(boxes):
            for direction in range(4):
                to = adj[box][direction]
                beyond = adj[to][direction] if to >= 0 else -1
                if to not in reachable or beyond < 0 or beyond in boxes:
                    continue
                moved = (boxes - {box}) | {to}
                state = (min(_walk(beyond, moved, adj)), moved)
                if state not in seen:
                    seen[state] = depth + 1
                    queue.append(state)
    return floor, seen


def _generate_sokoban(seed, tier):
    rng = random.Random(f"jev-sokoban-v1:{seed}:{tier}")
    count, lo, hi, min_push = (3, 36, 55, 12) if tier == "hard" else (4, 56, 80, 18)
    for attempt in range(2_000):
        floor = {(x, y) for x in range(1, 7) for y in range(1, 7)}
        for _ in range(rng.randrange(3, 10)):
            removed = rng.choice(sorted(floor))
            trial = floor - {removed}
            if len(_component(trial, min(trial))) == len(trial):
                floor = trial
        if not 26 <= len(floor) <= 36:
            continue
        goals = rng.sample(sorted(floor), count)
        data = {"width": 8, "height": 8, "floor": list(map(list, sorted(floor))),
                "goals": list(map(list, goals)), "boxes": [], "player": []}
        coordinates, states = _reverse_sokoban_states(data)
        candidates = [(state, depth) for state, depth in states.items() if depth >= min_push]
        rng.shuffle(candidates)
        for (player, boxes), _ in candidates[:15]:
            data["player"] = list(coordinates[player])
            data["boxes"] = [list(coordinates[p]) for p in sorted(boxes)]
            if tier == "harder" and _sokoban_solve(data, push_cost=True, lock_goals=True)["distance"] is not None:
                continue
            solution = _sokoban_solve(data)
            if solution["distance"] is None or not lo <= solution["distance"] <= hi:
                continue
            record = {"family": "sokoban", "tier": tier, "seed": seed,
                      "goal": "Push every box onto a goal. No pulling, undo, or reset.",
                      "data": copy.deepcopy(data), "certificate": {},
                      "reference_actions": _actions(solution["path"])}
            try:
                record["certificate"] = certify(record)
            except ValueError:
                continue
            return record
    raise RuntimeError("No Sokoban board passes exact gates within 2,000 authoring layouts; no unproven fallback")


def generate(family: str, seed: int, tier: str) -> dict:
    if tier not in ("hard", "harder") or not isinstance(seed, int):
        raise ValueError("tier must be hard/harder and seed an integer")
    if family == "key_maze":
        return _generate_maze(seed, tier)
    if family != "sokoban":
        raise ValueError(f"unsupported family: {family}")
    return _generate_sokoban(seed, tier)


def certify(record: dict) -> dict:
    family, tier, data = record["family"], record["tier"], record["data"]
    if tier not in ("hard", "harder"):
        raise ValueError("invalid tier")
    floor = set(map(tuple, data["floor"]))
    if len(floor) != len(data["floor"]) or tuple(data["player"]) not in floor:
        raise ValueError("invalid floor or player")
    if _component(floor, tuple(data["player"])) != floor:
        raise ValueError("floor must form one connected component")
    if any(not (0 <= x < data["width"] and 0 <= y < data["height"]) for x, y in floor):
        raise ValueError("floor outside board")
    if family == "sokoban":
        hard = tier == "hard"
        lo, hi, pushes, boxes = (36, 55, 12, 3) if hard else (56, 80, 18, 4)
        if (data["width"], data["height"]) != (8, 8) or not 26 <= len(floor) <= 36:
            raise ValueError("Sokoban dimensions/floor gate failed")
        box_set, goal_set = set(map(tuple, data["boxes"])), set(map(tuple, data["goals"]))
        if len(box_set) != boxes or len(goal_set) != boxes or not (box_set | goal_set) <= floor:
            raise ValueError("invalid box/goal placement")
        if tuple(data["player"]) in box_set:
            raise ValueError("player overlaps box")
        moves = _sokoban_solve(data)
        push_result = _sokoban_solve(data, push_cost=True)
        if moves["distance"] is None or not lo <= moves["distance"] <= hi or push_result["distance"] < pushes:
            raise ValueError(f"Sokoban distance gate failed: moves={moves['distance']}, pushes={push_result['distance']}")
        locked = _sokoban_solve(data, push_cost=True, lock_goals=True)
        if not hard and locked["distance"] is not None:
            raise ValueError("harder level does not require vacating a goal")
        deadlock = _deadlock_witness(data)
        if deadlock is None:
            raise ValueError("no certified reachable irreversible deadlock")
        result = {"version": 1, "minimum_moves": moves["distance"], "minimum_pushes": push_result["distance"],
                  "exact_move_states": moves["states"], "exact_push_states": push_result["states"],
                  "goal_lock_unsolvable": locked["distance"] is None, "goal_lock_states": locked["states"],
                  "deadlock_witness": deadlock}
    elif family == "key_maze":
        hard = tier == "hard"
        n, size, lo, hi = (3, 9, 45, 64) if hard else (4, 11, 65, 88)
        if (data["width"], data["height"]) != (size, size):
            raise ValueError("maze dimension gate failed")
        objects = [tuple(p) for p in data["keys"] + data["doors"]] + [tuple(data["player"]), tuple(data["exit"])]
        if len(data["keys"]) != n or len(data["doors"]) != n or len(set(objects)) != len(objects) or not set(objects) <= floor:
            raise ValueError("invalid maze objects")
        solution = _maze_bfs(data)
        structure = _maze_structure(data)
        if solution["distance"] is None or not lo <= solution["distance"] <= hi:
            raise ValueError("maze exact-distance gate failed")
        if structure["dependency_depth"] < n - 1 or structure["necessary_backtracks"] < n - 1:
            raise ValueError("maze dependency/backtrack gate failed")
        result = {"version": 1, "minimum_moves": solution["distance"], "exact_search_states": solution["states"], **structure}
    else:
        raise ValueError("unsupported game")
    env = Env(record)
    for action in record["reference_actions"]:
        step = env.step(action)
        if not step["valid"]:
            raise ValueError("reference path contains invalid action")
    if not env.success or len(record["reference_actions"]) != result["minimum_moves"]:
        raise ValueError("reference path does not win at certified distance")
    result["reference_atomic_actions"] = len(record["reference_actions"])
    result["reference_decision_calls"] = math.ceil(len(record["reference_actions"]) / 4)
    if result["reference_decision_calls"] > 24:
        raise ValueError("reference controller exceeds 24 calls")
    result["board_sha256"] = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return result


class Env:
    def __init__(self, record: dict):
        self.family = record["family"]
        self.goal = record["goal"]
        self.data = copy.deepcopy(record["data"])
        self.floor = set(map(tuple, self.data["floor"]))
        self.player = tuple(self.data["player"])
        self.boxes = set(map(tuple, self.data.get("boxes", [])))
        self.goals = set(map(tuple, self.data.get("goals", [])))
        self.keys = {tuple(p): i for i, p in enumerate(self.data.get("keys", []))}
        self.doors = {tuple(p): i for i, p in enumerate(self.data.get("doors", []))}
        self.held, self.opened = set(), set()
        self.done = self.success = False

    def step(self, action: dict) -> dict:
        if self.done:
            return {"valid": False, "terminal": True, "success": self.success, "reason": "episode already terminal"}
        if not isinstance(action, dict) or action.get("tool") != "press" or action.get("key") not in DELTA or set(action) != {"tool", "key"}:
            return {"valid": False, "terminal": False, "success": False, "reason": "expected one direction press"}
        dx, dy = DELTA[action["key"]]
        nxt = (self.player[0] + dx, self.player[1] + dy)
        if nxt not in self.floor:
            return {"valid": False, "terminal": False, "success": False, "reason": "wall"}
        if self.family == "sokoban" and nxt in self.boxes:
            beyond = (nxt[0] + dx, nxt[1] + dy)
            if beyond not in self.floor or beyond in self.boxes:
                return {"valid": False, "terminal": False, "success": False, "reason": "blocked box"}
            self.boxes.remove(nxt)
            self.boxes.add(beyond)
        if self.family == "key_maze":
            if nxt in self.doors:
                if self.doors[nxt] not in self.held:
                    return {"valid": False, "terminal": False, "success": False, "reason": "matching key required"}
                self.opened.add(self.doors[nxt])
            if nxt in self.keys:
                self.held.add(self.keys[nxt])
        self.player = nxt
        if self.family == "sokoban":
            self.success = self.boxes == self.goals
        else:
            self.success = (self.player == tuple(self.data["exit"]) and
                            len(self.held) == len(self.keys) and len(self.opened) == len(self.doors))
        self.done = self.success
        return {"valid": True, "terminal": self.done, "success": self.success,
                "reason": "complete" if self.success else "moved"}

    def render(self) -> Image.Image:
        image = Image.new("RGB", (768, 768), "#f3f6fc")
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=18)
        big = ImageFont.load_default(size=25)
        label = ImageFont.load_default(size=21)
        draw.text((28, 18), "SOKOBAN" if self.family == "sokoban" else "KEY & DOOR MAZE", font=big, fill="#172338")
        if self.family == "sokoban":
            lines = ["Arrows: move / push one box. Cover every red goal.",
                     "No pull, undo or reset. Green box = on a goal."]
        else:
            held = ", ".join(chr(65 + i) for i in sorted(self.held)) or "none"
            opened = ", ".join(chr(65 + i) for i in sorted(self.opened)) or "none"
            lines = ["Arrows: move. Keys stay held; matching doors open on entry.",
                     "Win: collect all keys, open all doors, reach EXIT.", f"Held: {held}     Open doors: {opened}"]
        for i, line in enumerate(lines):
            draw.text((28, 55 + i * 25), line, font=font, fill="#24344e")
        size = max(self.data["width"], self.data["height"])
        cell, left, top = 552 // size, 104, 178
        colors = ["#a43656", "#247499", "#817023", "#794fa3"]
        for x in range(self.data["width"]):
            draw.text((left + x * cell + cell // 2 - 6, top - 25), str(x), font=font, fill="#36445a")
        for y in range(self.data["height"]):
            draw.text((left - 25, top + y * cell + cell // 2 - 10), str(y), font=font, fill="#36445a")
            for x in range(self.data["width"]):
                p = (x, y)
                box = (left + x * cell, top + y * cell, left + (x + 1) * cell, top + (y + 1) * cell)
                draw.rectangle(box, fill="#fffefd" if p in self.floor else "#334155", outline="#c1cbd7", width=1)
                cx, cy = left + x * cell + cell // 2, top + y * cell + cell // 2
                if p in self.goals:
                    draw.ellipse((cx - 13, cy - 13, cx + 13, cy + 13), fill="#cf4555")
                if p in self.boxes:
                    draw.rounded_rectangle((box[0] + 7, box[1] + 7, box[2] - 7, box[3] - 7), radius=4,
                                           fill="#329568" if p in self.goals else "#bd8643", outline="#604a35", width=2)
                    draw.text((cx - 7, cy - 12), "*" if p in self.goals else "B", font=label, fill="white")
                if p in self.keys and self.keys[p] not in self.held:
                    draw.text((box[0] + 5, cy - 12), "k" + chr(65 + self.keys[p]), font=label, fill=colors[self.keys[p]])
                if p in self.doors:
                    i = self.doors[p]
                    draw.rectangle((box[0] + 4, box[1] + 4, box[2] - 4, box[3] - 4),
                                   outline=colors[i], width=2 if i in self.opened else 5)
                    draw.text((box[0] + 5, cy - 12), chr(65 + i) + ("+" if i in self.opened else ""), font=label, fill=colors[i])
                if self.family == "key_maze" and p == tuple(self.data["exit"]):
                    draw.text((box[0] + 3, cy - 10), "EXIT", font=ImageFont.load_default(size=14), fill="#1b7736")
                if p == self.player:
                    draw.ellipse((cx - 12, cy - 12, cx + 12, cy + 12), fill="#2666c9", outline="white", width=2)
                    draw.text((cx - 6, cy - 10), "P", font=font, fill="white")
        if self.success:
            draw.text((28, 735), "SUCCESS", font=font, fill="#187240")
        return image
