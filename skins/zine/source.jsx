// ZINE — xerox punk. Paper white, crushing black type, red tape strips, stamps,
// halftone dots, rotated labels. Archivo Black + Space Mono typewriter.

const ZN = {
  paper:"#f2efe6", ink:"#111111", red:"#d92b1c", grey:"#8a877c",
  font:"'Archivo Black', sans-serif", mono:"'Space Mono', monospace",
};

const znHalftone = "radial-gradient(circle, rgba(17,17,17,0.14) 1px, transparent 1.5px)";

function ZnTape({ style, color=ZN.red, w=120, r=-4 }) {
  return <div style={{position:"absolute", width:w, height:26, background:color, opacity:0.85,
    transform:`rotate(${r}deg)`, boxShadow:"0 1px 3px rgba(0,0,0,0.25)", ...style}}/>;
}

function ZnChrome({ children, page }) {
  return (
    <div className="ab" style={{width:1280, height:800, background:ZN.paper, color:ZN.ink, fontFamily:ZN.mono,
      position:"relative", overflow:"hidden",
      backgroundImage:`${znHalftone}`, backgroundSize:"7px 7px"}}>
      {/* masthead */}
      <div style={{height:62, borderBottom:`4px solid ${ZN.ink}`, display:"flex", alignItems:"center", padding:"0 24px", gap:20, background:ZN.paper}}>
        <span style={{fontFamily:ZN.font, fontSize:30, letterSpacing:"-0.02em"}}>BOOM ZINE</span>
        <span style={{fontSize:13, fontWeight:700, background:ZN.ink, color:ZN.paper, padding:"3px 10px", transform:"rotate(-1.5deg)"}}>{page}</span>
        <span style={{flex:1}}></span>
        <span style={{fontSize:12, letterSpacing:"0.1em", color:ZN.grey}}>ISSUE #04 · JULY '26</span>
        <span style={{fontSize:12, fontWeight:700, border:`2px solid ${ZN.red}`, color:ZN.red, padding:"2px 8px", transform:"rotate(2deg)", borderRadius:2}}>23:41</span>
      </div>
      {children}
    </div>
  );
}

function ZnBtn({ children, w, h=90, primary, rot=0, onClick }) {
  return (
    <button onClick={onClick} style={{
      width:w, height:h, background:primary?ZN.ink:ZN.paper, color:primary?ZN.paper:ZN.ink,
      border:`3px solid ${ZN.ink}`, cursor:"pointer", transform:`rotate(${rot}deg)`,
      fontFamily:ZN.font, fontSize:16, letterSpacing:"0.01em",
      display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:4,
      boxShadow:"3px 3px 0 rgba(17,17,17,0.9)", transition:"all .08s",
    }}>{children}</button>
  );
}

// ========== AUDIO ==========
function ZineAudio() {
  const [playing, setPlaying] = React.useState(true);
  const t = useTicker(120);
  const tr = TRACKS[6];
  return (
    <ZnChrome page="NOW PLAYING">
      <div style={{padding:"26px 30px", height:"calc(100% - 62px)", display:"grid", gridTemplateColumns:"1.25fr 1fr", gap:30}}>
        {/* Left: pasted-up title */}
        <div style={{position:"relative"}}>
          <ZnTape style={{top:-8, left:40}} r={-5}/>
          <ZnTape style={{top:-8, right:60}} color={ZN.ink} r={3} w={90}/>
          <div style={{background:ZN.paper, border:`3px solid ${ZN.ink}`, padding:"30px 32px", height:"100%",
            boxShadow:"6px 6px 0 rgba(17,17,17,0.9)", display:"flex", flexDirection:"column", justifyContent:"space-between", position:"relative"}}>
            <div>
              <div style={{fontSize:13, fontWeight:700, letterSpacing:"0.14em", marginBottom:14}}>
                *** TRACK NO. 07 — LOCAL TAPE ***
              </div>
              <div style={{fontFamily:ZN.font, fontSize:86, lineHeight:0.9, letterSpacing:"-0.04em", textTransform:"uppercase"}}>
                {tr.title}
              </div>
              <div style={{marginTop:18, fontSize:18, fontWeight:700}}>
                by {tr.artist.toUpperCase()}
              </div>
              <div style={{fontSize:13, color:ZN.grey, marginTop:4}}>from the record "{tr.album}" — {tr.time}</div>
            </div>
            {/* photocopier level meter: X's */}
            <div>
              <div style={{fontSize:12, fontWeight:700, letterSpacing:"0.14em", marginBottom:6}}>LOUDNESS:</div>
              <div style={{fontSize:22, letterSpacing:"0.1em", fontWeight:700}}>
                {Array.from({length:24}).map((_,i)=>{
                  const on = i < 8+Math.round(vu(t,3)*12);
                  return <span key={i} style={{color:on?(i>19?ZN.red:ZN.ink):"rgba(17,17,17,0.18)"}}>{on?"X":"·"}</span>;
                })}
              </div>
            </div>
            {/* stamp */}
            <div style={{position:"absolute", bottom:24, right:26, border:`3px solid ${ZN.red}`, color:ZN.red,
              padding:"8px 14px", fontFamily:ZN.font, fontSize:20, transform:"rotate(-8deg)", borderRadius:4, opacity:0.9}}>
              {playing ? "PLAYING" : "PAUSED"}
            </div>
          </div>
        </div>

        {/* Right: progress + transport + queue scraps */}
        <div style={{display:"flex", flexDirection:"column", gap:18}}>
          <div style={{position:"relative", background:ZN.paper, border:`3px solid ${ZN.ink}`, padding:"16px 20px", boxShadow:"4px 4px 0 rgba(17,17,17,0.9)"}}>
            <div style={{display:"flex", justifyContent:"space-between", fontSize:13, fontWeight:700, marginBottom:8}}>
              <span>1:12</span><span style={{letterSpacing:"0.18em"}}>SO FAR ─────</span><span>−1:30</span>
            </div>
            <div style={{height:22, border:`3px solid ${ZN.ink}`, position:"relative", background:ZN.paper}}>
              <div style={{position:"absolute", inset:0, width:"44%",
                background:`repeating-linear-gradient(45deg, ${ZN.ink} 0 6px, transparent 6px 12px)`}}/>
            </div>
          </div>

          <div style={{display:"grid", gridTemplateColumns:"1fr 1.3fr 1fr", gap:14}}>
            <ZnBtn h={110} rot={-1}><Icon name="prev" size={30} stroke="currentColor" sw={2.6}/>BACK</ZnBtn>
            <ZnBtn h={110} primary rot={1} onClick={()=>setPlaying(!playing)}>
              <Icon name={playing?"pause":"play"} size={44} stroke={ZN.paper} sw={2.6}/>
              {playing?"PAUSE!":"PLAY!"}
            </ZnBtn>
            <ZnBtn h={110} rot={-0.5}>NEXT<Icon name="next" size={30} stroke="currentColor" sw={2.6}/></ZnBtn>
          </div>
          <div style={{display:"grid", gridTemplateColumns:"repeat(4,1fr)", gap:10}}>
            <ZnBtn h={70} rot={0.8}><Icon name="shuffle" size={22} stroke="currentColor" sw={2.4}/></ZnBtn>
            <ZnBtn h={70} rot={-0.6}><Icon name="repeat" size={22} stroke="currentColor" sw={2.4}/></ZnBtn>
            <ZnBtn h={70} rot={0.4}><Icon name="queue" size={22} stroke="currentColor" sw={2.4}/></ZnBtn>
            <ZnBtn h={70} rot={-1}><Icon name="vol" size={22} stroke="currentColor" sw={2.4}/></ZnBtn>
          </div>

          {/* Up-next as a cut-out list */}
          <div style={{position:"relative", flex:1, background:ZN.paper, border:`3px solid ${ZN.ink}`, padding:"14px 18px",
            boxShadow:"4px 4px 0 rgba(17,17,17,0.9)", overflow:"hidden"}}>
            <ZnTape style={{top:-10, left:"38%"}} w={90} r={2}/>
            <div style={{fontFamily:ZN.font, fontSize:18, marginBottom:10}}>UP NEXT ↓</div>
            {TRACKS.slice(0,4).map((tk,i)=>(
              <div key={i} style={{display:"flex", gap:10, alignItems:"baseline", padding:"7px 0", borderBottom:`2px dashed rgba(17,17,17,0.25)`, fontSize:14}}>
                <span style={{fontWeight:700, color:ZN.red}}>{i+1}.</span>
                <span style={{fontWeight:700, flex:1, whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis"}}>{tk.title}</span>
                <span style={{color:ZN.grey, fontSize:12}}>{tk.artist}</span>
                <span style={{fontSize:12}}>{tk.time}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </ZnChrome>
  );
}

// ========== SOURCE ==========
function ZineSource() {
  const [sel, setSel] = React.useState("local");
  const rots = [-1.5, 1, -0.5, 1.5, -1, 0.5];
  return (
    <ZnChrome page="PICK YR SOURCE">
      <div style={{padding:"26px 30px", height:"calc(100% - 62px)", display:"flex", flexDirection:"column", gap:20}}>
        <div style={{fontFamily:ZN.font, fontSize:56, letterSpacing:"-0.03em", lineHeight:0.95}}>
          WHERE'S THE<br/><span style={{color:ZN.red}}>NOISE</span> COMING FROM?
        </div>
        <div style={{display:"grid", gridTemplateColumns:"repeat(3,1fr)", gridAutoRows:"1fr", gap:20, flex:1}}>
          {SOURCES.map((s,i)=>{
            const active = sel===s.id;
            return (
              <button key={s.id} onClick={()=>setSel(s.id)} style={{
                background: active?ZN.ink:ZN.paper, color:active?ZN.paper:ZN.ink,
                border:`3px solid ${ZN.ink}`, cursor:"pointer", padding:"18px 20px",
                transform:`rotate(${rots[i]}deg)`, position:"relative", textAlign:"left",
                boxShadow: active?`6px 6px 0 ${ZN.red}`:"4px 4px 0 rgba(17,17,17,0.9)",
                display:"flex", flexDirection:"column", justifyContent:"space-between",
                fontFamily:ZN.mono, transition:"all .1s",
              }}>
                <div style={{display:"flex", justifyContent:"space-between", alignItems:"center"}}>
                  <Icon name={s.icon} size={44} stroke={active?ZN.paper:ZN.ink} sw={2.2}/>
                  <span style={{fontSize:12, fontWeight:700, letterSpacing:"0.14em"}}>NO.{i+1}</span>
                </div>
                <div>
                  <div style={{fontFamily:ZN.font, fontSize:30, letterSpacing:"-0.02em"}}>{s.label}</div>
                  <div style={{fontSize:12, marginTop:6, opacity:0.75}}>{s.sub}</div>
                </div>
                {active && (
                  <div style={{position:"absolute", top:-14, right:-10, border:`3px solid ${ZN.red}`, color:ZN.red,
                    background:ZN.paper, padding:"5px 12px", fontFamily:ZN.font, fontSize:15, transform:"rotate(6deg)", borderRadius:3}}>
                    THIS ONE!
                  </div>
                )}
              </button>
            );
          })}
        </div>
        <div style={{display:"flex", gap:14, alignItems:"center"}}>
          <ZnBtn w={150} h={76} rot={-0.5}>NAH, BACK</ZnBtn>
          <span style={{flex:1, fontSize:13, fontWeight:700, textAlign:"right", paddingRight:10}}>
            → routing <span style={{color:ZN.red}}>{SOURCES.find(x=>x.id===sel).label}</span> thru the DAC…
          </span>
          <ZnBtn w={200} h={76} primary rot={0.5}>DO IT !!</ZnBtn>
        </div>
      </div>
    </ZnChrome>
  );
}

// ========== VIDEO ==========
function ZineVideo() {
  const [chrome, setChrome] = React.useState(true);
  return (
    <ZnChrome page="MOVIE NIGHT">
      <div onClick={()=>setChrome(!chrome)} style={{position:"relative", height:"calc(100% - 62px)", background:"#0d0c0a"}}>
        <div style={{position:"absolute", inset:0, opacity:0.9,
          background:"radial-gradient(ellipse at 45% 45%, rgba(217,43,28,0.25), transparent 50%), linear-gradient(180deg,#1c1310,#0d0c0a)"}}/>
        {/* halftone overlay on video too */}
        <div style={{position:"absolute", inset:0, backgroundImage:"radial-gradient(circle, rgba(242,239,230,0.05) 1px, transparent 1.6px)", backgroundSize:"6px 6px"}}/>
        <div style={{position:"absolute", inset:0, display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:16, color:ZN.paper}}>
          <div style={{fontSize:13, fontWeight:700, letterSpacing:"0.3em", fontFamily:ZN.mono}}>TONIGHT'S FEATURE ///</div>
          <div style={{fontFamily:ZN.font, fontSize:92, letterSpacing:"-0.04em", lineHeight:0.88, textAlign:"center",
            textShadow:`5px 5px 0 ${ZN.red}`}}>REPO<br/>MAN</div>
          <div style={{fontFamily:ZN.mono, fontSize:14, letterSpacing:"0.2em"}}>00:48:18 / 01:32:00</div>
        </div>
        {chrome && (
          <div style={{position:"absolute", left:20, right:20, bottom:18, background:ZN.paper, border:`3px solid ${ZN.ink}`,
            boxShadow:"5px 5px 0 rgba(0,0,0,0.5)", padding:"14px 20px", transform:"rotate(-0.3deg)"}}>
            <div style={{display:"flex", alignItems:"center", gap:12, marginBottom:12, fontFamily:ZN.mono}}>
              <span style={{fontSize:13, fontWeight:700}}>00:48:18</span>
              <div style={{flex:1, height:18, border:`3px solid ${ZN.ink}`, position:"relative"}}>
                <div style={{position:"absolute", inset:0, width:"52%",
                  background:`repeating-linear-gradient(45deg, ${ZN.red} 0 6px, transparent 6px 12px)`}}/>
              </div>
              <span style={{fontSize:13, fontWeight:700}}>−43:42</span>
            </div>
            <div style={{display:"flex", gap:10}}>
              <ZnBtn w={92} h={72} rot={-0.8}>−10</ZnBtn>
              <ZnBtn w={92} h={72} rot={0.5}><Icon name="prev" size={24} stroke="currentColor" sw={2.4}/></ZnBtn>
              <ZnBtn w={150} h={72} primary rot={-0.4}><Icon name="pause" size={28} stroke={ZN.paper} sw={2.4}/>PAUSE</ZnBtn>
              <ZnBtn w={92} h={72} rot={0.7}><Icon name="next" size={24} stroke="currentColor" sw={2.4}/></ZnBtn>
              <ZnBtn w={92} h={72} rot={-0.5}>+10</ZnBtn>
              <span style={{flex:1}}></span>
              <ZnBtn w={110} h={72} rot={0.6}>SUBS</ZnBtn>
              <ZnBtn w={110} h={72} rot={-0.7}>LOUD</ZnBtn>
            </div>
          </div>
        )}
      </div>
    </ZnChrome>
  );
}

Object.assign(window, { ZineAudio, ZineSource, ZineVideo });
