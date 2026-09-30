"""Behavioral tests for game physics, independently checked shortest paths,
authoring gates, and screenshot rendering. No model calls are used.
"""
import copy
from collections import deque
import unittest

from jevbench.push_maze import (
    DIRECTIONS, Env, _sokoban_solve, _topology, certify, generate,
)


def atomic_bfs(data):
    """Deliberately separate full atomic-state BFS to check contracted solver."""
    _, index, adjacency = _topology(data)
    initial = (index[tuple(data["player"])], frozenset(index[tuple(p)] for p in data["boxes"]))
    goals = frozenset(index[tuple(p)] for p in data["goals"])
    queue, seen = deque([(initial, 0)]), {initial}
    while queue:
        (player, boxes), depth = queue.popleft()
        if boxes == goals:
            return depth
        for direction, destination in enumerate(adjacency[player]):
            if destination < 0:
                continue
            moved = boxes
            if destination in boxes:
                beyond = adjacency[destination][direction]
                if beyond < 0 or beyond in boxes:
                    continue
                moved = (boxes - {destination}) | {beyond}
            nxt = (destination, moved)
            if nxt not in seen:
                seen.add(nxt)
                queue.append((nxt, depth + 1))
    return None


class PushMazeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sokoban = generate("sokoban", 177, "hard")
        cls.harder_sokoban = generate("sokoban", 177, "harder")
        cls.maze = generate("key_maze", 177, "harder")

    def test_exact_move_search_matches_independent_atomic_bfs(self):
        self.assertEqual(_sokoban_solve(self.sokoban["data"])["distance"],
                         atomic_bfs(self.sokoban["data"]))

    def test_certificates_recomputed_not_trusted(self):
        tampered = copy.deepcopy(self.sokoban)
        tampered["certificate"] = {"minimum_moves": 999999, "goal_lock_unsolvable": True}
        actual = certify(tampered)
        self.assertEqual(actual, self.sokoban["certificate"])

    def test_changed_reference_rejected(self):
        tampered = copy.deepcopy(self.maze)
        tampered["reference_actions"] = []
        with self.assertRaises(ValueError):
            certify(tampered)

    def test_harder_requires_moving_an_occupied_goal(self):
        record = self.harder_sokoban
        cert = certify(record)
        self.assertGreaterEqual(cert["minimum_moves"], 56)
        self.assertGreaterEqual(cert["minimum_pushes"], 18)
        self.assertTrue(cert["goal_lock_unsolvable"])
        env, vacated = Env(record), False
        for action in record["reference_actions"]:
            occupied = env.boxes & env.goals
            env.step(action)
            vacated |= bool(occupied - env.boxes)
        self.assertTrue(vacated)
        self.assertTrue(env.success)

    def test_certified_deadlock_is_legally_reachable_and_unsolvable(self):
        record = self.harder_sokoban
        env = Env(record)
        witness = record["certificate"]["deadlock_witness"]
        for direction in witness["path"]:
            self.assertTrue(env.step({"tool": "press", "key": DIRECTIONS[direction][0]})["valid"])
        self.assertIn(tuple(witness["dead_square"]), env.boxes)
        dead = copy.deepcopy(record["data"])
        dead["player"] = list(env.player)
        dead["boxes"] = list(map(list, env.boxes))
        self.assertIsNone(_sokoban_solve(dead)["distance"])

    def test_reference_wins_for_both_games(self):
        for record in (self.sokoban, self.maze):
            env = Env(record)
            for action in record["reference_actions"]:
                result = env.step(action)
                self.assertTrue(result["valid"])
            self.assertTrue(env.done and env.success)
            self.assertFalse(env.step({"tool": "press", "key": "up"})["valid"])

    def test_invalid_actions_do_not_mutate_state(self):
        env = Env(self.sokoban)
        before = (env.player, set(env.boxes))
        for action in ({"tool": "solve"}, {"tool": "press", "key": "up", "repeat": 10},
                       {"tool": "press", "key": "UP"}, []):
            self.assertFalse(env.step(action)["valid"])
            self.assertEqual(before, (env.player, env.boxes))

    def test_wall_is_recoverable(self):
        env = Env(self.maze)
        for name, dx, dy in DIRECTIONS:
            if (env.player[0] + dx, env.player[1] + dy) not in env.floor:
                result = env.step({"tool": "press", "key": name})
                self.assertFalse(result["valid"])
                self.assertFalse(result["terminal"])
                break
        else:
            self.fail("generated maze start should be a leaf")

    def test_locked_door_requires_key_and_key_is_retained(self):
        env = Env(self.maze)
        door, key_id = next(iter(env.doors.items()))
        for name, dx, dy in DIRECTIONS:
            neighbor = (door[0] - dx, door[1] - dy)
            if neighbor in env.floor:
                env.player = neighbor
                self.assertFalse(env.step({"tool": "press", "key": name})["valid"])
                env.held.add(key_id)
                self.assertTrue(env.step({"tool": "press", "key": name})["valid"])
                self.assertIn(key_id, env.held)
                self.assertIn(key_id, env.opened)
                break

    def test_sixteen_maze_instances_meet_gates_and_are_distinct(self):
        hashes = set()
        for tier in ("hard", "harder"):
            for seed in range(8):
                record = generate("key_maze", seed, tier)
                cert = certify(record)
                self.assertLessEqual(cert["reference_decision_calls"], 24)
                hashes.add(cert["board_sha256"])
        self.assertEqual(len(hashes), 16)

    def test_seed_reproduction(self):
        self.assertEqual(self.maze, generate("key_maze", 177, "harder"))
        self.assertEqual(self.sokoban, generate("sokoban", 177, "hard"))

    def test_readable_rgb_render(self):
        for record in (self.sokoban, self.maze):
            image = Env(record).render()
            self.assertEqual(image.size, (768, 768))
            self.assertEqual(image.mode, "RGB")
            self.assertGreater(len(image.getcolors(768 * 768)), 20)


if __name__ == "__main__":
    unittest.main()
