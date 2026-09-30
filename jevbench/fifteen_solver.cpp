// Authoring-only exact IDA* solver. Walking-distance abstraction is a lower bound.
#include <array>
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <iostream>
#include <queue>
#include <unordered_map>
#include <vector>
using namespace std;
using U=uint64_t;
unordered_map<U,uint8_t> wd;
U pack(const array<int,16>& a,int b){U k=b;for(int i=0;i<16;i++)k|=U(a[i])<<(2+3*i);return k;}
void table(){array<int,16>a{};a[0]=a[5]=a[10]=4;a[15]=3;U g=pack(a,3);wd[g]=0;queue<U>q;q.push(g);while(!q.empty()){U k=q.front();q.pop();int b=k&3;for(int i=0;i<16;i++)a[i]=(k>>(2+3*i))&7;for(int n:{b-1,b+1})if(n>=0&&n<4)for(int j=0;j<4;j++)if(a[n*4+j]){a[n*4+j]--;a[b*4+j]++;U v=pack(a,n);if(!wd.count(v)){wd[v]=wd[k]+1;q.push(v);}a[n*4+j]++;a[b*4+j]--;}}}
array<int,16> board;
vector<int> path;
long long nodes=0,limitnodes=100000000;
chrono::steady_clock::time_point deadline;
int heur(int z){array<int,16>r{},c{};for(int i=0;i<16;i++)if(board[i]){int goal=board[i]-1;r[(i/4)*4+goal/4]++;c[(i%4)*4+goal%4]++;}return wd.at(pack(r,z/4))+wd.at(pack(c,z%4));}
int dfs(int z,int prev,int depth,int bound){if((++nodes&65535)==0 &&(nodes>limitnodes||chrono::steady_clock::now()>deadline))return -2;int h=heur(z);if(!h)return -1;int f=depth+h;if(f>bound)return f;int best=999;array<pair<int,int>,4> moves;int nm=0;for(int n:{z-4,z+4,z-1,z+1})if(n>=0&&n<16&&n!=prev&&(abs(n-z)==4||n/4==z/4)){swap(board[z],board[n]);moves[nm++]={heur(n),n};swap(board[z],board[n]);}sort(moves.begin(),moves.begin()+nm);for(int i=0;i<nm;i++){int n=moves[i].second;swap(board[z],board[n]);path.push_back(n);int got=dfs(n,z,depth+1,bound);if(got<0)return got;path.pop_back();swap(board[z],board[n]);best=min(best,got);}return best;}
int main(int argc,char**argv){if(argc<17)return 2;for(int i=0;i<16;i++)board[i]=stoi(argv[i+1]);int sec=argc>17?stoi(argv[17]):30;limitnodes=argc>18?stoll(argv[18]):100000000;table();deadline=chrono::steady_clock::now()+chrono::seconds(sec);int z=find(board.begin(),board.end(),0)-board.begin();int initial=heur(z),bound=initial;while(bound<=80){int r=dfs(z,-1,0,bound);if(r==-1){cout<<"{\"optimal\":"<<path.size()<<",\"initial_lower_bound\":"<<initial<<",\"nodes\":"<<nodes<<",\"path\":[";for(size_t i=0;i<path.size();i++){if(i)cout<<",";cout<<path[i];}cout<<"]}"<<endl;return 0;}if(r==-2){cout<<"{\"timeout\":true,\"proved_lower_bound\":"<<bound<<",\"nodes\":"<<nodes<<"}"<<endl;return 3;}bound=r;}return 4;}
