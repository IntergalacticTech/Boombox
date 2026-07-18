// FLIGHT DECK — avionics MFD. Vector-green lines on near-black, bezel softkeys
// down both sides (real hardware feel for gloves), DM Mono data blocks.

const FLT = {
  bg:"#060807", bezel:"#0d100e", ink:"#c9d6c8", green:"#57e389", greenDim:"#1e4a2e",
  cyan:"#6bd7e8", amber:"#f5c451", red:"#f26d5b", rule:"rgba(87,227,137,0.18)",
  mono:"'DM Mono', monospace", font:"'Space Grotesk', sans-serif",
};

function FltSoftkey({ children, side, active, onClick }) {
  return (
    <button onClick={onClick} style={{
      height:76, width:"100%", background: active?"rgba(87,227,137,0.10)":FLT.bezel,
      border:`1px solid ${active?FLT.green:FLT.rule}`, borderRadius:4,
      color:active?FLT.green:FLT.ink, fontFamily:FLT.mono, fontSize:12, letterSpacing:"0.14em",
      cursor:"pointer", display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:3,
      textAlign:"center", padding:"0 6px", transition:"all .1s",
    }}>{children}</button>
  );
}

function FltChrome({ children, page="AUD", keysL=[], keysR=[] }) {
  const t = useTicker(500);
  return (
    <div className="ab" style={{width:1280, height:800, background:FLT.bg, color:FLT.ink, fontFamily:FLT.mono, position:"relative", overflow:"hidden", display:"flex"}}>
      {/* Left softkeys */}
      <div style={{width:130, padding:"64px 10px 14px", display:"flex", flexDirection:"column", gap:10, background:FLT.bezel, borderRight:`1px solid ${FLT.rule}`}}>
        {keysL.map((k,i)=><FltSoftkey key={i} active={k.active}>{k.label}</FltSoftkey>)}
      </div>
      {/* Screen */}
      <div style={{flex:1, position:"relative", display:"flex", flexDirection:"column"}}>
        <div style={{height:44, display:"flex", alignItems:"center", padding:"0 20px", gap:16, borderBottom:`1px solid ${FLT.rule}`, fontSize:12, letterSpacing:"0.2em"}}>
          <span style={{color:FLT.green, fontWeight:500}}>BBX-MFD</span>
          <span style={{color:FLT.greenDim}}>│</span>
          <span style={{color:FLT.cyan}}>PAGE {page}</span>
          <span style={{flex:1}}></span>
          <span style={{color:FLT.amber}}>DAC OK</span>
          <span style={{color:FLT.greenDim}}>│</span>
          <span>NET −52</span>
          <span style={{color:FLT.greenDim}}>│</span>
          <span style={{color:FLT.green}}>{t%2?"23:41:08Z":"23:41:08Z"}</span>
        </div>
        <div style={{flex:1, position:"relative",
          backgroundImage:"radial-gradient(circle at 50% 50%, rgba(87,227,137,0.03), transparent 70%)"}}>{children}</div>
      </div>
      {/* Right softkeys */}
      <div style={{width:130, padding:"64px 10px 14px", display:"flex", flexDirection:"column", gap:10, background:FLT.bezel, borderLeft:`1px solid ${FLT.rule}`}}>
        {keysR.map((k,i)=><FltSoftkey key={i} active={k.active}>{k.label}</FltSoftkey>)}
      </div>
    </div>
  );
}

// Arc gauge — vector style, like an engine N1 dial
function FltArc({ value, label, unit, size=210, color=FLT.green }) {
  const a0=-210, a1=30, a = a0 + value*(a1-a0);
  const rad = d=>d*Math.PI/180;
  const R=78;
  const pt = d=>[Math.cos(rad(d))*R, Math.sin(rad(d))*R];
  const [x0,y0]=pt(a0), [x1,y1]=pt(a1), [xa,ya]=pt(a);
  return (
    <div style={{width:size, textAlign:"center"}}>
      <svg viewBox="-100 -100 200 160" style={{width:"100%"}}>
        <path d={`M ${x0} ${y0} A ${R} ${R} 0 1 1 ${x1} ${y1}`} fill="none" stroke={FLT.greenDim} strokeWidth="3"/>
        <path d={`M ${x0} ${y0} A ${R} ${R} 0 ${(a-a0)>180?1:0} 1 ${xa} ${ya}`} fill="none" stroke={color} strokeWidth="3"/>
        {Array.from({length:9}).map((_,i)=>{
          const d=a0+(i/8)*(a1-a0), [tx,ty]=pt(d), [tx2,ty2]=[Math.cos(rad(d))*(R-9), Math.sin(rad(d))*(R-9)];
          return <line key={i} x1={tx} y1={ty} x2={tx2} y2={ty2} stroke={FLT.ink} strokeWidth="1"/>;
        })}
        <line x1="0" y1="0" x2={Math.cos(rad(a))*(R-14)} y2={Math.sin(rad(a))*(R-14)} stroke={color} strokeWidth="2.4"/>
        <circle cx="0" cy="0" r="3.5" fill={color}/>
        <text x="0" y="44" textAnchor="middle" fill={color} fontSize="22" fontFamily={FLT.mono}>{Math.round(value*100)}</text>
        <text x="0" y="58" textAnchor="middle" fill={FLT.ink} fontSize="8" fontFamily={FLT.mono} letterSpacing="2">{unit}</text>
      </svg>
      <div style={{fontSize:12, letterSpacing:"0.24em", color:FLT.ink, marginTop:-8}}>{label}</div>
    </div>
  );
}

// ========== AUDIO ==========
function FlightAudio() {
  const [playing, setPlaying] = React.useState(true);
  const t = useTicker(80);
  const tr = TRACKS[4];
  const keysL = [
    {label:<><b>AUD</b><span style={{fontSize:10, color:FLT.greenDim}}>PAGE</span></>, active:true},
    {label:<>LIB</>}, {label:<>SRC</>}, {label:<>VID</>}, {label:<>SET</>},
  ];
  const keysR = [
    {label:<>⇄ SHUF</>}, {label:<>↻ RPT</>}, {label:<>QUEUE</>}, {label:<>MARK</>}, {label:<>DIM</>},
  ];
  return (
    <FltChrome page="AUD 1/3" keysL={keysL} keysR={keysR}>
      <div style={{padding:"20px 26px", height:"100%", display:"flex", flexDirection:"column", gap:14}}>
        {/* Track data block */}
        <div style={{border:`1px solid ${FLT.rule}`, padding:"14px 20px", display:"grid", gridTemplateColumns:"1fr auto", gap:20}}>
          <div>
            <div style={{fontSize:11, color:FLT.cyan, letterSpacing:"0.26em", marginBottom:8}}>ACTIVE TRACK · 05/17 · LOCAL</div>
            <div style={{fontFamily:FLT.font, fontSize:42, fontWeight:600, color:FLT.green, lineHeight:1, letterSpacing:"-0.01em"}}>{tr.title}</div>
            <div style={{fontSize:15, marginTop:8, color:FLT.ink}}>{tr.artist} <span style={{color:FLT.greenDim}}>//</span> {tr.album}</div>
          </div>
          <div style={{textAlign:"right", display:"flex", flexDirection:"column", justifyContent:"center"}}>
            <div style={{fontSize:11, color:FLT.greenDim, letterSpacing:"0.26em"}}>ELAPSED</div>
            <div style={{fontSize:46, color:FLT.amber, fontVariantNumeric:"tabular-nums", lineHeight:1}}>02:06</div>
            <div style={{fontSize:13, color:FLT.ink, marginTop:2}}>REM 01:47</div>
          </div>
        </div>
        {/* Gauges row */}
        <div style={{display:"flex", justifyContent:"space-around", alignItems:"center", flex:1, border:`1px solid ${FLT.rule}`}}>
          <FltArc value={0.45+vu(t,1)*0.4} label="LEVEL L" unit="dBFS"/>
          <FltArc value={0.45+vu(t,2)*0.4} label="LEVEL R" unit="dBFS"/>
          <FltArc value={0.62} label="VOLUME" unit="PCT" color={FLT.amber}/>
          <FltArc value={196/tr.len} label="POSITION" unit="PCT" color={FLT.cyan}/>
        </div>
        {/* Progress tape + transport */}
        <div style={{border:`1px solid ${FLT.rule}`, padding:"12px 18px"}}>
          <div style={{display:"flex", alignItems:"center", gap:12, marginBottom:12}}>
            <span style={{fontSize:12, color:FLT.cyan}}>TRK</span>
            <div style={{flex:1, height:10, border:`1px solid ${FLT.greenDim}`, position:"relative"}}>
              <div style={{position:"absolute", inset:1, width:"54%", background:`repeating-linear-gradient(90deg, ${FLT.green} 0 5px, transparent 5px 7px)`}}/>
              <div style={{position:"absolute", left:"54%", top:-4, width:2, height:16, background:FLT.amber}}/>
            </div>
            <span style={{fontSize:12, color:FLT.ink}}>{tr.time}</span>
          </div>
          <div style={{display:"flex", gap:10}}>
            <button onClick={()=>{}} style={fltTBtn()}>|◀ PREV</button>
            <button onClick={()=>setPlaying(!playing)} style={fltTBtn(true)}>{playing?"▮▮ PAUSE":"▶ PLAY"}</button>
            <button style={fltTBtn()}>NEXT ▶|</button>
            <span style={{flex:1}}></span>
            <button style={fltTBtn()}>VOL −</button>
            <button style={fltTBtn()}>VOL +</button>
          </div>
        </div>
      </div>
    </FltChrome>
  );
}

function fltTBtn(primary) {
  return {
    height:76, padding:"0 28px", background:primary?"rgba(87,227,137,0.12)":FLT.bezel,
    border:`1px solid ${primary?FLT.green:FLT.rule}`, borderRadius:4, color:primary?FLT.green:FLT.ink,
    fontFamily:FLT.mono, fontSize:15, letterSpacing:"0.14em", cursor:"pointer", fontWeight:primary?600:400,
  };
}

// ========== SOURCE ==========
function FlightSource() {
  const [sel, setSel] = React.useState(0);
  const keysL = SOURCES.slice(0,5).map((s,i)=>({label:<>{s.label}</>, active:i===sel}));
  const keysR = [{label:<>SCAN</>}, {label:<>PAIR</>}, {label:<>INFO</>}, {label:<>TEST</>}, {label:<><b style={{color:FLT.amber}}>EXEC ↵</b></>}];
  return (
    <FltChrome page="SRC 1/1" keysL={keysL} keysR={keysR}>
      <div style={{padding:"20px 26px", height:"100%", display:"flex", flexDirection:"column", gap:14}}>
        <div style={{fontSize:12, color:FLT.cyan, letterSpacing:"0.26em"}}>INPUT ROUTING · SELECT WITH BEZEL KEYS OR TAP</div>
        <div style={{flex:1, border:`1px solid ${FLT.rule}`, display:"flex", flexDirection:"column"}}>
          {SOURCES.map((s,i)=>{
            const active = i===sel;
            return (
              <button key={s.id} onClick={()=>setSel(i)} style={{
                flex:1, display:"grid", gridTemplateColumns:"70px 60px 1fr 1fr 160px", alignItems:"center", gap:16,
                padding:"0 22px", background:active?"rgba(87,227,137,0.08)":"transparent",
                border:"none", borderBottom:`1px solid ${FLT.rule}`, cursor:"pointer",
                color:active?FLT.green:FLT.ink, fontFamily:FLT.mono, textAlign:"left",
              }}>
                <span style={{fontSize:13, color:active?FLT.amber:FLT.greenDim, letterSpacing:"0.2em"}}>L{i+1}</span>
                <Icon name={s.icon} size={30} stroke={active?FLT.green:FLT.ink} sw={1.5}/>
                <span style={{fontFamily:FLT.font, fontSize:26, fontWeight:600, letterSpacing:"0.02em"}}>{s.label}</span>
                <span style={{fontSize:13, color:active?FLT.ink:FLT.greenDim}}>{s.sub}</span>
                <span style={{fontSize:13, letterSpacing:"0.18em", textAlign:"right", color:active?FLT.amber:FLT.greenDim}}>
                  {active?"■ ROUTED":"□ STBY"}
                </span>
              </button>
            );
          })}
        </div>
        <div style={{border:`1px solid ${FLT.rule}`, padding:"12px 18px", display:"flex", alignItems:"center", gap:14, fontSize:13}}>
          <span style={{color:FLT.cyan, letterSpacing:"0.2em"}}>ROUTE</span>
          <span style={{color:FLT.green}}>{SOURCES[sel].label}</span>
          <span style={{color:FLT.greenDim}}>→</span>
          <span>DAC pcm5122</span>
          <span style={{color:FLT.greenDim}}>→</span>
          <span>AMP OUT</span>
          <span style={{flex:1}}></span>
          <span style={{color:FLT.amber}}>PRESS EXEC TO CONFIRM</span>
        </div>
      </div>
    </FltChrome>
  );
}

// ========== VIDEO ==========
function FlightVideo() {
  const [chrome, setChrome] = React.useState(true);
  const keysL = [{label:<>AUD</>}, {label:<>LIB</>}, {label:<>SRC</>}, {label:<><b>VID</b></>, active:true}, {label:<>SET</>}];
  const keysR = [{label:<>SUB EN</>}, {label:<>AUD 5.1</>}, {label:<>CHAP</>}, {label:<>ZOOM</>}, {label:<>OSD</>}];
  return (
    <FltChrome page="VID 1/1" keysL={keysL} keysR={keysR}>
      <div onClick={()=>setChrome(!chrome)} style={{position:"absolute", inset:0, background:"#000"}}>
        <div style={{position:"absolute", inset:0,
          background:"radial-gradient(ellipse at 40% 45%, rgba(87,227,137,0.10), transparent 50%), radial-gradient(circle at 70% 60%, rgba(107,215,232,0.10), transparent 45%), linear-gradient(180deg,#03110a,#000)"}}/>
        <div style={{position:"absolute", inset:0, display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:12}}>
          <div style={{fontSize:12, color:FLT.cyan, letterSpacing:"0.3em"}}>VIDEO FEED · 1080P · H264</div>
          <div style={{fontFamily:FLT.font, fontSize:76, fontWeight:700, color:FLT.ink, letterSpacing:"-0.02em"}}>TOP GUN</div>
          <div style={{fontSize:14, color:FLT.green, letterSpacing:"0.2em"}}>01:24:18 / 01:50:00 · CH 12</div>
        </div>
        {/* HUD-style corner data */}
        <div style={{position:"absolute", top:14, left:20, fontSize:11, color:FLT.green, letterSpacing:"0.18em", lineHeight:1.9}}>
          FPS 23.98<br/>BUF 96%<br/>SYNC OK
        </div>
        {chrome && (
          <div style={{position:"absolute", left:0, right:0, bottom:0, padding:"16px 24px",
            background:"linear-gradient(0deg, rgba(0,0,0,0.9), transparent)"}}>
            <div style={{display:"flex", alignItems:"center", gap:12, marginBottom:12, fontSize:13}}>
              <span style={{color:FLT.amber, fontVariantNumeric:"tabular-nums"}}>01:24:18</span>
              <div style={{flex:1, height:8, border:`1px solid ${FLT.greenDim}`, position:"relative"}}>
                <div style={{position:"absolute", inset:1, width:"77%", background:FLT.green, opacity:0.8}}/>
                <div style={{position:"absolute", left:"77%", top:-4, width:2, height:14, background:FLT.amber}}/>
              </div>
              <span style={{color:FLT.ink, fontVariantNumeric:"tabular-nums"}}>−25:42</span>
            </div>
            <div style={{display:"flex", gap:10}}>
              <button style={fltTBtn()}>−10S</button>
              <button style={fltTBtn()}>|◀</button>
              <button style={fltTBtn(true)}>▮▮ PAUSE</button>
              <button style={fltTBtn()}>▶|</button>
              <button style={fltTBtn()}>+10S</button>
              <span style={{flex:1}}></span>
              <button style={fltTBtn()}>FULL ⛶</button>
            </div>
          </div>
        )}
      </div>
    </FltChrome>
  );
}

Object.assign(window, { FlightAudio, FlightSource, FlightVideo });
