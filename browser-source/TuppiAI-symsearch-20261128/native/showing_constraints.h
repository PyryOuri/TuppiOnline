/* Showing-fallback restrictions for the ordinary sampler (B0-S1; ported from
 * tuppi_execution_sampler_v1/native_capture, where it was validated against
 * exhaustive enumeration and engine replays).
 *
 * A shown card constrains the shower's ORIGINAL hand beyond ownership: an
 * eligible card of the colour opposite to the declared contract means the hand
 * had no eligible card of the requested colour; an ineligible rank means it had
 * no eligible rank at all. Observations with no such restriction keep the
 * original sampling path and rng use.
 *
 * Exact counting sampler for rank-dependent forbidden placements.
 * Each full assignment corresponds to one path through this DP. Drawing each
 * next seat proportional to its completion count gives uniform assignments.
 * Public fallback shows constrain the ORIGINAL hand, including played cards.
 */
#define SHOW_ELIGIBLE (0xFEULL | (0xFEULL<<13) | (0xFEULL<<26) | (0xFEULL<<39))
#define SHOW_RED (SUIT_MASK(0) | SUIT_MASK(1))

static double tc_research_draw_constrained(const int others[3], const int cap[3],
                                   u64 free_cards, const u64 forbidden[4],
                                   u64 *rng, u64 hands[4]) {
  int cards[52], allowed[52], n=0;
  for (u64 m=free_cards;m;m&=m-1) {
    int c=__builtin_ctzll(m);cards[n]=c;allowed[n]=0;
    for(int j=0;j<3;j++) if(!(forbidden[others[j]]>>c&1ULL)) allowed[n]|=1<<j;
    n++;
  }
  for(int j=0;j<3;j++) if(cap[j]<0 || cap[j]>13) return 0;
  if(n!=cap[0]+cap[1]+cap[2]) return 0;
  double ways[53][14][14]={0};ways[n][0][0]=1;
  for(int i=n-1;i>=0;i--) for(int a=0;a<=cap[0];a++) for(int b=0;b<=cap[1];b++) {
    int c=n-i-a-b;
    if(c<0 || c>cap[2]) continue;
    if(a && (allowed[i]&1)) ways[i][a][b]+=ways[i+1][a-1][b];
    if(b && (allowed[i]&2)) ways[i][a][b]+=ways[i+1][a][b-1];
    if(c && (allowed[i]&4)) ways[i][a][b]+=ways[i+1][a][b];
  }
  double total=ways[0][cap[0]][cap[1]];
  if(!rng || total==0) return total;
  int a=cap[0],b=cap[1];
  for(int i=0;i<n;i++) {
    int c=n-i-a-b;
    double w[3]={a && (allowed[i]&1) ? ways[i+1][a-1][b]:0,
                 b && (allowed[i]&2) ? ways[i+1][a][b-1]:0,
                 c && (allowed[i]&4) ? ways[i+1][a][b]:0};
    double x=unit(rng)*(w[0]+w[1]+w[2]);int selected=-1,last=-1;
    for(int j=0;j<3;j++) if(w[j]>0) {last=j;if(x<w[j]) {selected=j;break;} x-=w[j];}
    if(selected<0) selected=last; /* floating point boundary only */
    if(selected<0) return 0;
    hands[others[selected]]|=1ULL<<cards[i];
    if(selected==0) a--;else if(selected==1) b--;
  }
  return total;
}

static int showing_forbidden(const TcObs *o, u64 forbidden[4]) {
  int active=0;
  if(TC_LOCKED(o)) return 0; /* unrevealed bids must not leak */
  for(int i=0;i<o->n_shows;i++) {
    int c=o->show_card[i],s=o->show_seat[i],k=o->show_contract[i];
    u64 colour=k==TC_RAMI ? SHOW_RED : (FULL_DECK & ~SHOW_RED);
    if(!(SHOW_ELIGIBLE>>c&1ULL)) forbidden[s]|=SHOW_ELIGIBLE;
    else if(!(colour>>c&1ULL)) forbidden[s]|=SHOW_ELIGIBLE & colour;
    active |= forbidden[s]!=0;
  }
  return active;
}
