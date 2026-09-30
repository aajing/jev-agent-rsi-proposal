import copy
from collections import deque
import itertools
import json
import random
from pathlib import Path
import unittest
from jevbench.mines_puzzle import (Env,cell_action,certify,global_inference,
    _component_models,neighbors,solve_fifteen,manhattan,mines_reference)

FIXTURES=Path(__file__).parent/'fixtures'

class GamesTests(unittest.TestCase):
    def load(self,family,tier='hard'):
        return json.loads((FIXTURES/f'{family}-{tier}.json').read_text())

    def test_all_public_fixtures_recertify(self):
        for family in ['minesweeper','fifteen-puzzle']:
            for tier in ['hard','harder']:
                with self.subTest(family=family,tier=tier):
                    result=certify(self.load(family,tier))
                    self.assertTrue(result['valid'])
                    self.assertLessEqual(result['reference_calls'],24)
                    self.assertLessEqual(result['reference_atomic_attempts'],96)

    def test_stored_certificate_cannot_forge_difficulty(self):
        r=self.load('fifteen-puzzle')
        r['data']['board']=list(range(1,16))+[0]
        with self.assertRaises(ValueError):certify(r)
        r=self.load('minesweeper');r['data']['mines']=[]
        with self.assertRaises(ValueError):certify(r)

    def test_tampered_reference_rejected(self):
        r=self.load('minesweeper');r['reference_batches'][0][0]={'tool':'click','x':-1,'y':-1}
        with self.assertRaises(ValueError):certify(r)

    def test_mines_noop_and_invalid_click_preserve_state(self):
        env=Env(self.load('minesweeper'));before=set(env.revealed)
        result=env.step(cell_action(min(before),env.n))
        self.assertTrue(result['valid']);self.assertEqual('already_revealed',result['reason'])
        self.assertEqual(before,env.revealed)
        self.assertFalse(env.step({'tool':'click','x':True,'y':0})['valid'])
        self.assertFalse(env.step({'tool':'click','x':-1,'y':-1})['valid'])
        self.assertEqual(before,env.revealed)

    def test_mine_click_fails(self):
        env=Env(self.load('minesweeper'))
        result=env.step(cell_action(min(env.mines),env.n))
        self.assertTrue(result['valid']);self.assertTrue(result['terminal']);self.assertFalse(result['success'])

    def test_render_is_rgb_screenshot(self):
        for family in ['minesweeper','fifteen-puzzle']:
            image=Env(self.load(family)).render()
            self.assertEqual(image.mode,'RGB');self.assertEqual(image.size,(768,820))

    def test_native_solver_exact_small_distances(self):
        goal=list(range(1,16))+[0]
        self.assertEqual(solve_fifteen(goal)['optimal'],0)
        board=goal[:];board[14],board[15]=board[15],board[14]
        self.assertEqual(solve_fifteen(board)['optimal'],1)
        board[10],board[14]=board[14],board[10]
        self.assertEqual(solve_fifteen(board)['optimal'],2)

    def test_native_exact_distances_against_independent_bfs(self):
        goal=tuple(list(range(1,16))+[0]);distances={goal:0};queue=deque([goal]);examples={}
        while queue:
            state=queue.popleft();depth=distances[state]
            examples.setdefault(depth,state)
            if depth==8:continue
            blank=state.index(0)
            for adjacent in [blank-4,blank+4,blank-1,blank+1]:
                if not(0<=adjacent<16 and (abs(adjacent-blank)==4 or adjacent//4==blank//4)):continue
                new=list(state);new[blank],new[adjacent]=new[adjacent],new[blank];new=tuple(new)
                if new not in distances:distances[new]=depth+1;queue.append(new)
        for depth,state in examples.items():
            self.assertEqual(solve_fifteen(list(state))['optimal'],depth)

    def test_component_enumerator_matches_exhaustive_models(self):
        variables=list(range(6));equations=[({0,1,2},1),({1,3,4},2),({2,4,5},1)]
        expected={}
        for bits in itertools.product([0,1],repeat=6):
            if all(sum(bits[v] for v in cells)==rhs for cells,rhs in equations):
                count=sum(bits);mask=sum(bit<<i for i,bit in enumerate(bits))
                expected[count]=expected.get(count,0)|mask
        self.assertEqual(_component_models(variables,equations),expected)

    def test_global_safety_matches_bruteforce_from_visible_information(self):
        n=3;clues={0:1,3:1,6:0};total=2
        unknown=set(range(n*n))-set(clues);models=[]
        for chosen in itertools.combinations(unknown,total):
            mines=set(chosen)
            if all(len(set(neighbors(i,n))&mines)==v for i,v in clues.items()):models.append(mines)
        self.assertTrue(models)
        expected=unknown-set.union(*models)
        self.assertEqual(global_inference({'n':n,'total_mines':total,'clues':clues}),expected)

    def test_random_small_global_safety_matches_bruteforce(self):
        rng=random.Random(910)
        for _ in range(50):
            mines=set(rng.sample(range(9),rng.randint(1,3)))
            safe=sorted(set(range(9))-mines)
            revealed=rng.sample(safe,rng.randint(1,len(safe)))
            clues={i:len(set(neighbors(i,3))&mines) for i in revealed}
            unknown=set(range(9))-set(clues);models=[]
            for chosen in itertools.combinations(unknown,len(mines)):
                model=set(chosen)
                if all(len(set(neighbors(i,3))&model)==v for i,v in clues.items()):models.append(model)
            expected=unknown-set.union(*models)
            self.assertEqual(global_inference({'n':3,'total_mines':len(mines),'clues':clues}),expected)

    def test_every_mines_batch_is_safe_from_prebatch_information(self):
        for tier in ['hard','harder']:
            env=Env(self.load('minesweeper',tier))
            for batch in env.record['reference_batches']:
                safe=global_inference(env.observation())
                safe_actions=[cell_action(i,env.n) for i in safe]
                for action in batch:self.assertIn(action,safe_actions)
                for action in batch:
                    env.step(action)
                    if env.done:break
            self.assertTrue(env.success)

    def test_unsatisfiable_global_evidence_rejected(self):
        with self.assertRaises(ValueError):
            global_inference({'n':2,'total_mines':0,'clues':{0:1}})

    def test_illegal_puzzle_click_is_recoverable(self):
        env=Env(self.load('fifteen-puzzle'));before=env.board[:]
        result=env.step(cell_action(env.board.index(0),4))
        self.assertFalse(result['valid']);self.assertFalse(result['terminal']);self.assertEqual(env.board,before)
        for action in env.record['reference_actions']:env.step(action)
        self.assertTrue(env.success)

if __name__=='__main__':unittest.main()
