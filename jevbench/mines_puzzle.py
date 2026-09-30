"""Screenshot-only Minesweeper and fifteen-puzzle engines and authoring certificates.

Solvers and record['data'] are evaluator-private; agents receive render() only.
The exact constraint enumerator and native IDA* helper are authoring-only, never actor tools.
"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import random
import shutil
import subprocess
from collections import deque
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ORIGIN = (70, 140)
GRID = 630
TIERS = {'hard', 'harder'}


def geometry(n):
    return {'left': ORIGIN[0], 'top': ORIGIN[1], 'cell': GRID // n, 'n': n}


def cell_action(index, n):
    g = geometry(n)
    return {'tool': 'click', 'x': g['left'] + (index % n)*g['cell'] + g['cell']//2,
            'y': g['top'] + (index // n)*g['cell'] + g['cell']//2}


def neighbors(i, n):
    r, c = divmod(i, n)
    return [rr*n+cc for rr in range(max(0,r-1),min(n,r+2))
            for cc in range(max(0,c-1),min(n,c+2)) if (rr,cc)!=(r,c)]


def _font(size):
    for p in ['/System/Library/Fonts/Supplemental/Arial.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']:
        if Path(p).exists(): return ImageFont.truetype(p,size)
    return ImageFont.load_default(size=size)


class Env:
    def __init__(self, record):
        self.record = copy.deepcopy(record)
        self.family = record['family']
        self.data = record['data']
        self.goal = record['goal']
        self.done = self.success = False
        self.reason = 'active'
        if self.family == 'minesweeper':
            self.n = self.data['n']
            self.mines = set(self.data['mines'])
            self.revealed = set()
            self._reveal(self.data['initial'])
        elif self.family == 'fifteen_puzzle':
            self.n = 4
            self.board = list(self.data['board'])
        else: raise ValueError('Unknown family')

    def _reveal(self, i):
        if i in self.mines:
            self.done = True; self.reason = 'mine_hit'; return
        queue = deque([i])
        while queue:
            j = queue.popleft()
            if j in self.revealed: continue
            self.revealed.add(j)
            if not sum(k in self.mines for k in neighbors(j,self.n)):
                queue.extend(k for k in neighbors(j,self.n) if k not in self.revealed)
        self.success = len(self.revealed) == self.n*self.n-len(self.mines)
        self.done = self.success
        if self.success: self.reason = 'complete'

    def observation(self):
        """Authoring controller's ONLY Minesweeper input: public visible clues."""
        if self.family != 'minesweeper': raise ValueError('Minesweeper only')
        return {'n':self.n,'total_mines':len(self.mines),
                'clues':{i:sum(j in self.mines for j in neighbors(i,self.n)) for i in self.revealed}}

    def step(self, action):
        if self.done: return {'valid':False,'terminal':True,'success':self.success,'reason':'already_terminal'}
        if not isinstance(action,dict) or action.get('tool')!='click' or set(action)!={'tool','x','y'}:
            return {'valid':False,'terminal':False,'success':False,'reason':'invalid_action'}
        x,y=action['x'],action['y']; g=geometry(self.n)
        if type(x) is not int or type(y) is not int or not(g['left']<=x<g['left']+self.n*g['cell'] and g['top']<=y<g['top']+self.n*g['cell']):
            return {'valid':False,'terminal':False,'success':False,'reason':'outside_grid'}
        index=((y-g['top'])//g['cell'])*self.n+(x-g['left'])//g['cell']
        if self.family=='minesweeper':
            noop=index in self.revealed
            self._reveal(index)
            reason='already_revealed' if noop else self.reason
        else:
            blank=self.board.index(0)
            if abs(index//4-blank//4)+abs(index%4-blank%4)!=1:
                return {'valid':False,'terminal':False,'success':False,'reason':'tile_not_adjacent'}
            self.board[blank],self.board[index]=self.board[index],self.board[blank]
            self.success=self.board==list(range(1,16))+[0]; self.done=self.success
            reason='complete' if self.success else 'moved'
        return {'valid':True,'terminal':self.done,'success':self.success,'reason':reason}

    def render(self):
        im=Image.new('RGB',(768,820),'#f1f5f9'); d=ImageDraw.Draw(im)
        title='NO-GUESS MINESWEEPER' if self.family=='minesweeper' else 'FIFTEEN PUZZLE'
        d.text((35,20),title,font=_font(27),fill='#0f172a')
        subtitle=(f'{len(self.mines)} mines | Reveal every safe cell | No flags'
                  if self.family=='minesweeper' else 'Slide adjacent tiles | Goal: 1-15 then blank')
        d.text((35,63),subtitle,font=_font(20),fill='#334155')
        d.text((35,94),'One click = one cell. Row / column labels start at 1.',font=_font(16),fill='#334155')
        g=geometry(self.n); c=g['cell']
        for k in range(self.n):
            d.text((g['left']+k*c+c/2,g['top']-15),str(k+1),font=_font(16),anchor='mm',fill='#334155')
            d.text((g['left']-18,g['top']+k*c+c/2),str(k+1),font=_font(16),anchor='mm',fill='#334155')
        colors=['#64748b','#2563eb','#15803d','#dc2626','#7c3aed','#b45309','#0891b2','#111827','#475569']
        for i in range(self.n*self.n):
            x=g['left']+(i%self.n)*c;y=g['top']+(i//self.n)*c
            text=''; color='#0f172a'
            if self.family=='minesweeper':
                visible=i in self.revealed
                fill='#e2e8f0' if visible else '#475569'
                if visible:
                    value=sum(j in self.mines for j in neighbors(i,self.n))
                    text=str(value) if value else ''
                    color=colors[value]
                elif self.done and not self.success and i in self.mines: text='*';color='#fca5a5'
            else:
                v=self.board[i];fill='#ffffff' if v else '#334155';text=str(v) if v else ''
            d.rectangle((x+1,y+1,x+c-2,y+c-2),fill=fill,outline='#94a3b8',width=2)
            d.text((x+c/2,y+c/2),text,font=_font(int(c*.40)),anchor='mm',fill=color)
        return im


def _constraints(obs, known_mines, known_safe):
    unseen=set(range(obs['n']**2))-set(obs['clues'])
    out={}
    for i,value in obs['clues'].items():
        near=set(neighbors(i,obs['n']))
        cells=frozenset((near&unseen)-known_mines-known_safe)
        count=value-len(near&known_mines)
        if count<0 or count>len(cells): raise ValueError('Inconsistent local evidence')
        if cells:
            if cells in out and out[cells]!=count: raise ValueError('Contradictory constraints')
            out[cells]=count
    return out


def local_inference(obs, known_mines=(), known_safe=()):
    """Adjacent-clue direct/subset elimination to a fixed point.

    Total-count boundary cases (zero/all remaining cells are mines) are local.
    Combining nontrivial global mine totals with components belongs to global
    inference, by the task's explicitly fixed definition of the local baseline.
    """
    mines=set(known_mines);safe=set(known_safe)-set(obs['clues'])
    while True:
        unseen=set(range(obs['n']**2))-set(obs['clues'])
        remaining=unseen-mines-safe
        left=obs['total_mines']-len(mines)
        if left<0 or left>len(remaining):raise ValueError('Inconsistent total mine count')
        if left==0:safe|=remaining
        elif left==len(remaining):mines|=remaining
        constraints=_constraints(obs,mines,safe)
        changed=True
        while changed:
            changed=False
            items=list(constraints.items())
            for a,va in items:
                for b,vb in items:
                    if a<b:
                        diff=b-a;value=vb-va
                        if value<0 or value>len(diff): raise ValueError('Bad subset inference')
                        if diff not in constraints:
                            constraints[diff]=value;changed=True
                            if len(constraints)>3000:raise ValueError('Subset closure exceeded authoring budget')
        new_s=set();new_m=set()
        for cells,count in constraints.items():
            if count==0:new_s.update(cells)
            if count==len(cells):new_m.update(cells)
        if not(new_s-safe or new_m-mines):return mines,safe
        safe|=new_s;mines|=new_m


def frontier_size(obs, known=()):
    unseen=set(range(obs['n']**2))-set(obs['clues'])-set(known);adj={}
    for i in obs['clues']:
        cells=set(neighbors(i,obs['n']))&unseen
        for c in cells:adj.setdefault(c,set()).update(cells-{c})
    best=0;todo=set(adj)
    while todo:
        start=todo.pop();q=[start];size=0
        while q:
            i=q.pop();size+=1
            for j in adj[i]&todo:todo.remove(j);q.append(j)
        best=max(best,size)
    return best


def _component_models(variables, equations, node_limit=200000):
    """Exhaustive Boolean PB models, summarized losslessly by mine count.

    For each count, the OR of all model masks says exactly which cells CAN
    contain mines. A zero bit therefore proves safety at that count.
    """
    index={v:i for i,v in enumerate(variables)}
    constraints=[(sum(1<<index[v] for v in cells),rhs) for cells,rhs in equations]
    full=(1<<len(variables))-1;models={};nodes=0
    def visit(ones,zeros):
        nonlocal nodes
        nodes+=1
        if nodes>node_limit:raise ValueError('Global model enumeration exceeded authoring budget')
        while True:
            before=ones|zeros
            for mask,rhs in constraints:
                unknown=mask&~(ones|zeros);left=rhs-(mask&ones).bit_count();size=unknown.bit_count()
                if left<0 or left>size:return
                if left==0:zeros|=unknown
                elif left==size:ones|=unknown
                if ones&zeros:return
            if (ones|zeros)==before:break
        if (ones|zeros)==full:
            count=ones.bit_count();models[count]=models.get(count,0)|ones;return
        available=full&~(ones|zeros)
        # Branch on the smallest residual clue to maximize propagation.
        residual=[mask&available for mask,_ in constraints if mask&available]
        tight=min(residual,key=int.bit_count) if residual else available
        bit=tight&-tight
        visit(ones,zeros|bit);visit(ones|bit,zeros)
    visit(0,0)
    return models


def global_inference(obs):
    """Exact SAT via complete component model enumeration + global mine count.

    Inputs are ONLY visible clues, dimensions, and the publicly stated total.
    Enumeration must finish; incomplete search is rejected, never a certificate.
    """
    unseen=set(range(obs['n']**2))-set(obs['clues'])
    equations=[];adj={}
    for cell,value in obs['clues'].items():
        group=set(neighbors(cell,obs['n']))&unseen
        if not group:
            if value:raise ValueError('Impossible clue')
            continue
        equations.append((group,value))
        for v in group:adj.setdefault(v,set()).update(group-{v})
    pending=set(adj);components=[]
    while pending:
        start=pending.pop();group={start};queue=[start]
        while queue:
            v=queue.pop()
            for w in adj[v]&pending:pending.remove(w);group.add(w);queue.append(w)
        variables=sorted(group)
        models=_component_models(variables,[(g,r) for g,r in equations if g<=group])
        if not models:raise ValueError('Visible constraints are unsatisfiable')
        components.append((variables,models))
    free=sorted(unseen-set(adj));count_sets=[set(models) for _,models in components]+[set(range(len(free)+1))]
    def sums(sets):
        values={0}
        for group in sets:values={a+b for a in values for b in group if a+b<=obs['total_mines']}
        return values
    if obs['total_mines'] not in sums(count_sets):raise ValueError('Global evidence not satisfiable')
    safe=set()
    for k,(variables,models) in enumerate(components):
        other=sums(count_sets[:k]+count_sets[k+1:]);possible=0
        for count,mask in models.items():
            if obs['total_mines']-count in other:possible|=mask
        safe.update(v for i,v in enumerate(variables) if not(possible>>i)&1)
    other=sums(count_sets[:-1]);feasible_free={c for c in count_sets[-1] if obs['total_mines']-c in other}
    if feasible_free=={0}:safe.update(free)
    return safe


def mines_reference(record):
    env=Env(record);known_mines=set();known_safe=set();batches=[];stages=[];maximum=0;attempts=0
    while not env.done:
        obs=env.observation()
        known_mines,known_safe=local_inference(obs,known_mines,known_safe)
        if not known_safe:
            frontier=frontier_size(obs,known_mines);maximum=max(maximum,frontier)
            known_safe=global_inference(obs)
            if not known_safe:raise ValueError('Board requires guessing')
            stages.append({'revealed':len(obs['clues']),'frontier':frontier,
                           'safe':sorted(known_safe),
                           'visible_sha256':hashlib.sha256(json.dumps(obs,sort_keys=True).encode()).hexdigest()})
        # All selected clicks are safe from the SAME pre-batch information.
        selected=sorted(known_safe)[:4]
        batch=[cell_action(i,env.n) for i in selected]
        batches.append(batch)
        for action in batch:
            attempts+=1
            outcome=env.step(action)
            if not outcome['valid'] or (outcome['terminal'] and not outcome['success']):raise AssertionError('Invalid reference')
            if env.done:break
        known_safe-=env.revealed
        if len(batches)>24:raise ValueError('Reference exceeds 24 calls')
    return {'algorithm':'complete_component_enumeration_with_global_mine_count',
            'global_stages':len(stages),'max_frontier':maximum,'stages':stages,
            'reference_calls':len(batches),'reference_atomic_attempts':attempts},batches


def _native_solver():
    exe=HERE/'.fifteen_solver';src=HERE/'fifteen_solver.cpp'
    if not exe.exists() or exe.stat().st_mtime<src.stat().st_mtime:
        compiler=shutil.which('c++') or shutil.which('clang++') or shutil.which('g++')
        if not compiler:raise RuntimeError('A C++17 compiler is required for fifteen-puzzle authoring certificates')
        subprocess.run([compiler,'-O3','-std=c++17',str(src),'-o',str(exe)],check=True,capture_output=True)
    return exe


def solve_fifteen(board,seconds=15,node_limit=5_000_000):
    if sorted(board)!=list(range(16)):raise ValueError('Invalid fifteen-puzzle permutation')
    result=subprocess.run([str(_native_solver()),*map(str,board),str(seconds),str(node_limit)],capture_output=True,text=True,timeout=seconds+5)
    if result.returncode:raise ValueError('Exact fifteen-puzzle proof exceeded authoring limit')
    return json.loads(result.stdout)


def manhattan(board):
    return sum(abs(i//4-(v-1)//4)+abs(i%4-(v-1)%4) for i,v in enumerate(board) if v)


def _base(family,seed,tier,data):
    goal=('Reveal every non-mine cell without clicking a mine. Total mines and initial clues are visible.'
          if family=='minesweeper' else 'Restore tiles 1 through 15 in row-major order, with the blank in the bottom-right cell.')
    return {'family':family,'seed':seed,'tier':tier,'goal':goal,'data':data}


def generate(family,seed:int,tier:str):
    """Deterministic rejection sampling; raises rather than relaxing any gate."""
    if tier not in TIERS:raise ValueError('tier must be hard or harder')
    rng=random.Random(seed)
    if family=='minesweeper':
        n,count,stages,frontier=(8,10,2,12) if tier=='hard' else (9,16,4,18)
        initial=(n//2)*n+n//2
        forbidden=set(neighbors(initial,n))|{initial}
        choices=sorted(set(range(n*n))-forbidden)
        for attempt in range(50000):
            record=_base(family,seed,tier,{'n':n,'mines':sorted(rng.sample(choices,count)),'initial':initial})
            try:certificate,batches=mines_reference(record)
            except ValueError:continue
            if certificate['global_stages']>=stages and certificate['max_frontier']>=frontier:
                certificate['candidate_attempt']=attempt
                record.update(certificate=certificate,reference_batches=batches,reference_actions=[a for b in batches for a in b])
                return record
        raise RuntimeError('No certified minesweeper instance found within 50000 candidates')
    if family=='fifteen_puzzle':
        lo,hi,gap=(35,44,6) if tier=='hard' else (45,54,10)
        for attempt in range(2000):
            board=list(range(1,16))+[0];blank=15;prev=-1
            for _ in range(90 if tier=='hard' else 140):
                choices=[j for j in [blank-4,blank+4,blank-1,blank+1] if 0<=j<16 and j!=prev and(abs(j-blank)==4 or j//4==blank//4)]
                j=rng.choice(choices);board[blank],board[j]=board[j],board[blank];prev,blank=blank,j
            md=manhattan(board)
            if md>hi-gap:continue
            try:proof=solve_fifteen(board)
            except ValueError:continue
            distance=proof['optimal']
            if lo<=distance<=hi and distance-md>=gap:
                record=_base(family,seed,tier,{'board':board})
                actions=[cell_action(i,4) for i in proof['path']]
                proof.update(manhattan=md,gap=distance-md,algorithm='exact_ida_star_walking_distance',candidate_attempt=attempt)
                proof['reference_calls']=(distance+3)//4;proof['reference_atomic_attempts']=distance
                record.update(certificate=proof,reference_actions=actions,reference_batches=[actions[i:i+4] for i in range(0,len(actions),4)])
                return record
        raise RuntimeError('No certified fifteen-puzzle instance found within authoring budget')
    raise ValueError('Unsupported family')


def certify(record):
    """Recompute difficulty from source state; never trust the stored certificate."""
    family=record['family'];tier=record['tier']
    if tier not in TIERS:raise ValueError('Invalid tier')
    if family=='minesweeper':
        n,count,stages,frontier=(8,10,2,12) if tier=='hard' else (9,16,4,18)
        data=record['data'];mines=data['mines'];initial=data['initial']
        if data['n']!=n or len(set(mines))!=count or len(mines)!=count or any(type(m) is not int or not 0<=m<n*n for m in mines):raise ValueError('Invalid mine layout')
        if not 0<=initial<n*n or (set(neighbors(initial,n))|{initial})&set(mines):raise ValueError('Initial cell must be zero and safe')
        proof,batches=mines_reference(record)
        if proof['global_stages']<stages or proof['max_frontier']<frontier:raise ValueError('Minesweeper difficulty gate failed')
        if record.get('reference_batches')!=batches:raise ValueError('Reference batches differ from visible-only controller')
    elif family=='fifteen_puzzle':
        board=record['data']['board'];lo,hi,gap=(35,44,6) if tier=='hard' else (45,54,10)
        proof=solve_fifteen(board,seconds=60,node_limit=20_000_000);md=manhattan(board)
        if not lo<=proof['optimal']<=hi or proof['optimal']-md<gap:raise ValueError('Fifteen-puzzle difficulty gate failed')
        proof.update(manhattan=md,gap=proof['optimal']-md)
    else:raise ValueError('Unsupported family')
    env=Env(record);batches=record.get('reference_batches',[])
    if len(batches)>24 or any(not 1<=len(b)<=4 for b in batches):raise ValueError('Reference call limit failed')
    atoms=0
    for batch in batches:
        if env.done:raise ValueError('Reference contains post-terminal batch')
        for action in batch:
            atoms+=1
            if atoms>96:raise ValueError('Reference atomic limit failed')
            result=env.step(action)
            if not result['valid']:raise ValueError('Illegal reference action')
            if env.done:break
    if not env.success:raise ValueError('Reference did not win')
    flat=[a for batch in batches for a in batch]
    if record.get('reference_actions')!=flat:raise ValueError('Reference action flattening mismatch')
    proof.update(reference_calls=len(batches),reference_atomic_attempts=atoms,valid=True)
    return proof
