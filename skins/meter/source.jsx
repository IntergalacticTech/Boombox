// METER — analog VU/gauge worship, flattened to digital primitives.
// Cream paper + ink black + safety-orange peak. No drawn cassettes.
// Big circular dial gauges, big tabular numerals, hairline rules.

const MTR = {
  bg:       "#ece6d8",
  paper:    "#f4efe2",
  ink:      "#16140e",
  ink2:     "#5a5345",
  rule:     "#cdc5b1",
  ruleHi:   "#1c1a13",
  amber:    "#e26a1f",
  red:      "#c93a2a",
  green:    "#3a7a4a",
  cream:    "#fbf6e8",
  font:     "'Space Grotesk', -apple-system, system-ui, sans-serif",
  mono:     "'JetBrains Mono', monospace",
};

function MtrChrome({ children, label="01 · NOW PLAYING" }) {
  return (
    <div className="ab" style={{
      width:1280, height:800, background:MTR.bg, color:MTR.ink, fontFamily:MTR.font,
      position:"relative", overflow:"hidden",
    }}>
      <div style={{
        height:54, padding:"0 28px", display:"flex", alignItems:"center", gap:18,
        borderBottom:`1px solid ${MTR.ruleHi}`, background:MTR.paper,
        fontFamily:MTR.mono, fontSize:12, letterSpacing:"0.18em", textTransform:"uppercase",
      }}>
        <span style={{fontWeight:700, fontSize:14, letterSpacing:"0.32em"}}>METER · BOOMBOX</span>
        <span style={{color:MTR.ink2}}>—</span>
        <span style={{color:MTR.ink2}}>{label}</span>
        <span style={{flex:1}}></span>
        <span>48k · 24bit</span>
        <span style={{color:MTR.ink2}}>|</span>
        <span style={{color:MTR.amber}}>● LOCAL</span>
        <span style={{color:MTR.ink2}}>|</span>
        <span style={{fontVariantNumeric:"tabular-nums"}}>23:41</span>
      </div>
      {children}
    </div>
  );
}

// Half-circle needle gauge.
function NeedleGauge({ value = 0.6, label, peak, size = 320, danger = 0.85 }) {
  // value 0..1 → angle from -120° to +120° (centered at 12 o'clock)
  const angle = -120 + value * 240;
  const ticks = Array.from({length: 21});
  return (
    <div style={{
      width:size, height:size*0.78, position:"relative",
      background:MTR.cream, border:`1px solid ${MTR.ruleHi}`,
      padding:"14px 16px 0", display:"flex", flexDirection:"column",
    }}>
      <div style={{display:"flex", justifyContent:"space-between", alignItems:"baseline", fontFamily:MTR.mono, fontSize:11, letterSpacing:"0.18em"}}>
        <span style={{fontWeight:700}}>{label}</span>
        <span style={{color:MTR.ink2}}>VU · dB</span>
      </div>
      <svg viewBox="-100 -90 200 110" style={{width:"100%", flex:1, marginTop:4}}>
        {/* arc */}
        <path d="M -78 0 A 78 78 0 0 1 78 0" fill="none" stroke={MTR.ink} strokeWidth="0.8"/>
        {/* danger zone arc */}
        <path d="M 49 -60.7 A 78 78 0 0 1 78 0" fill="none" stroke={MTR.red} strokeWidth="3"/>
        {/* ticks */}
        {ticks.map((_, i) => {
          const t = i / 20;
          const a = (-120 + t * 240) * Math.PI / 180;
          const r1 = 78, r2 = (i % 5 === 0) ? 64 : 71;
          const x1 = Math.sin(a) * r1, y1 = -Math.cos(a) * r1;
          const x2 = Math.sin(a) * r2, y2 = -Math.cos(a) * r2;
          return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke={t > 0.85 ? MTR.red : MTR.ink} strokeWidth={i % 5 === 0 ? 1.4 : 0.6}/>;
        })}
        {/* labels */}
        {[
          {t:0,   v:"−∞"}, {t:0.25, v:"−20"}, {t:0.5, v:"−10"}, {t:0.7, v:"−3"}, {t:0.85, v:"0"}, {t:1, v:"+3"},
        ].map(({t,v}) => {
          const a = (-120 + t * 240) * Math.PI / 180;
          const r = 56;
          const x = Math.sin(a) * r, y = -Math.cos(a) * r;
          return <text key={v} x={x} y={y+3} fill={t>0.85?MTR.red:MTR.ink} fontSize="6.5" fontFamily={MTR.mono} textAnchor="middle">{v}</text>;
        })}
        {/* needle */}
        <g style={{transform:`rotate(${angle}deg)`, transformOrigin:"0 0", transition:"transform 0.18s ease-out"}}>
          <line x1="0" y1="6" x2="0" y2="-72" stroke={value>danger?MTR.red:MTR.ruleHi} strokeWidth="1.8" strokeLinecap="round"/>
          <circle cx="0" cy="0" r="4" fill={MTR.ruleHi}/>
        </g>
      </svg>
      <div style={{position:"absolute", left:0, right:0, bottom:8, textAlign:"center", fontFamily:MTR.mono, fontSize:11, letterSpacing:"0.16em", color:MTR.ink2}}>
        peak <span style={{color:value>danger?MTR.red:MTR.ink, fontWeight:700}}>{peak ?? `−${(20 - value*22).toFixed(1)} dB`}</span>
      </div>
    </div>
  );
}

function MtrButton({ children, w=120, h=88, active, onClick, big }) {
  return (
    <button onClick={onClick} style={{
      width:w, height:h, border:`1.5px solid ${MTR.ruleHi}`,
      background: active ? MTR.ink : MTR.cream,
      color: active ? MTR.cream : MTR.ink,
      fontFamily: MTR.mono, fontSize: big?15:12, fontWeight:700,
      letterSpacing:"0.18em", textTransform:"uppercase", cursor:"pointer",
      display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:6,
      boxShadow: active ? `2px 2px 0 ${MTR.amber}` : `2px 2px 0 ${MTR.ruleHi}`,
      transition:"all .08s",
    }}>{children}</button>
  );
}

// ========== AUDIO ==========
function MeterAudio() {
  const [playing, setPlaying] = React.useState(true);
  const t = useTicker(80);
  const tr = TRACKS[1];
  const lpk = vu(t, 1), rpk = vu(t, 2);

  return (
    <MtrChrome label="01 · AUDIO">
      <div style={{padding:"24px 28px", height:"calc(100% - 54px)", display:"grid", gridTemplateColumns:"1.2fr 1fr", gap:24}}>
        {/* Left: meters + numerics */}
        <div style={{display:"flex", flexDirection:"column", gap:18}}>
          <div style={{display:"flex", gap:14}}>
            <NeedleGauge value={0.5 + lpk * 0.4} label="LEFT" size={320} peak={`−${(8 - lpk*8).toFixed(1)} dB`}/>
            <NeedleGauge value={0.5 + rpk * 0.4} label="RIGHT" size={320} peak={`−${(8 - rpk*8).toFixed(1)} dB`}/>
          </div>

          {/* 3-band EQ as small bar gauges */}
          <div style={{background:MTR.cream, border:`1px solid ${MTR.ruleHi}`, padding:"16px 20px"}}>
            <div style={{display:"flex", justifyContent:"space-between", fontFamily:MTR.mono, fontSize:11, letterSpacing:"0.18em", marginBottom:14}}>
              <span style={{fontWeight:700}}>EQ · 3 BAND</span>
              <span style={{color:MTR.ink2}}>POST</span>
            </div>
            <div style={{display:"grid", gridTemplateColumns:"1fr 1fr 1fr", gap:30}}>
              {[{l:"BASS", v:0.7, hz:"60Hz"}, {l:"MID", v:0.45, hz:"1kHz"}, {l:"TREB", v:0.6, hz:"8kHz"}].map((b,i)=>(
                <div key={i}>
                  <div style={{display:"flex", justifyContent:"space-between", fontFamily:MTR.mono, fontSize:11, marginBottom:6}}>
                    <span style={{fontWeight:700}}>{b.l}</span>
                    <span style={{color:MTR.ink2}}>{b.hz}</span>
                  </div>
                  <div style={{height:14, background:MTR.bg, border:`1px solid ${MTR.ruleHi}`, position:"relative"}}>
                    <div style={{position:"absolute", left:0, top:0, bottom:0, width:`${b.v*100}%`, background:MTR.ink}}/>
                    {/* center mark */}
                    <div style={{position:"absolute", left:"50%", top:-2, bottom:-2, width:1, background:MTR.amber}}/>
                  </div>
                  <div style={{fontFamily:MTR.mono, fontSize:11, color:MTR.ink2, marginTop:4, textAlign:"right"}}>
                    {b.v > 0.5 ? "+" : ""}{((b.v-0.5)*12).toFixed(1)} dB
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Right: track + transport */}
        <div style={{display:"flex", flexDirection:"column", gap:18}}>
          <div style={{background:MTR.paper, border:`1px solid ${MTR.ruleHi}`, padding:"22px 24px"}}>
            <div style={{fontFamily:MTR.mono, fontSize:11, letterSpacing:"0.22em", color:MTR.ink2, marginBottom:8}}>
              TRACK · 04 / 17 · MP3 · 320
            </div>
            <div style={{fontSize:34, fontWeight:700, lineHeight:1.05, letterSpacing:"-0.02em"}}>
              {tr.title}
            </div>
            <div style={{fontSize:18, color:MTR.ink2, marginTop:6}}>
              {tr.artist} · <em style={{color:MTR.ink}}>{tr.album}</em>
            </div>

            {/* Counter */}
            <div style={{marginTop:22, display:"flex", alignItems:"baseline", justifyContent:"space-between", borderTop:`1px solid ${MTR.rule}`, paddingTop:18}}>
              <div>
                <div style={{fontFamily:MTR.mono, fontSize:10, letterSpacing:"0.22em", color:MTR.ink2}}>ELAPSED</div>
                <div style={{fontFamily:MTR.mono, fontSize:46, fontWeight:700, lineHeight:1, fontVariantNumeric:"tabular-nums"}}>
                  01:24
                </div>
              </div>
              <div style={{textAlign:"right"}}>
                <div style={{fontFamily:MTR.mono, fontSize:10, letterSpacing:"0.22em", color:MTR.ink2}}>REMAIN</div>
                <div style={{fontFamily:MTR.mono, fontSize:46, fontWeight:700, lineHeight:1, fontVariantNumeric:"tabular-nums", color:MTR.amber}}>
                  −1:07
                </div>
              </div>
            </div>

            {/* Tape-counter style progress (no skeumorphism, just hash marks) */}
            <div style={{marginTop:14, height:6, background:MTR.bg, border:`1px solid ${MTR.ruleHi}`, position:"relative"}}>
              <div style={{position:"absolute", left:0, top:0, bottom:0, width:"56%", background:MTR.ink}}/>
            </div>
          </div>

          {/* Transport */}
          <div style={{display:"grid", gridTemplateColumns:"1fr 1fr 1fr", gap:10}}>
            <MtrButton h={96}><Icon name="prev" size={26}/>PREV</MtrButton>
            <MtrButton h={96} big active={playing} onClick={()=>setPlaying(!playing)}>
              <Icon name={playing?"pause":"play"} size={36} stroke={MTR.cream}/>
              {playing ? "PAUSE" : "PLAY"}
            </MtrButton>
            <MtrButton h={96}><Icon name="next" size={26}/>NEXT</MtrButton>
          </div>
          <div style={{display:"grid", gridTemplateColumns:"1fr 1fr 1fr 1fr", gap:8}}>
            <MtrButton h={68}><Icon name="shuffle" size={20}/></MtrButton>
            <MtrButton h={68}><Icon name="repeat" size={20}/></MtrButton>
            <MtrButton h={68}><Icon name="queue" size={20}/></MtrButton>
            <MtrButton h={68}><Icon name="search" size={20}/></MtrButton>
          </div>

          {/* Volume slider */}
          <div style={{background:MTR.cream, border:`1px solid ${MTR.ruleHi}`, padding:"14px 18px"}}>
            <div style={{display:"flex", justifyContent:"space-between", fontFamily:MTR.mono, fontSize:11, letterSpacing:"0.18em", marginBottom:8}}>
              <span style={{fontWeight:700}}>VOLUME</span>
              <span style={{color:MTR.amber}}>−14 dB · 62%</span>
            </div>
            <div style={{height:12, background:MTR.bg, border:`1px solid ${MTR.ruleHi}`, position:"relative"}}>
              <div style={{position:"absolute", left:0, top:0, bottom:0, width:"62%", background:`repeating-linear-gradient(90deg, ${MTR.ink} 0 6px, transparent 6px 8px)`}}/>
              <div style={{position:"absolute", left:"62%", top:-4, bottom:-4, width:6, background:MTR.amber, border:`1px solid ${MTR.ruleHi}`}}/>
            </div>
          </div>
        </div>
      </div>
    </MtrChrome>
  );
}

// ========== SOURCE ==========
function MeterSource() {
  const [sel, setSel] = React.useState("local");
  return (
    <MtrChrome label="02 · INPUT SELECTOR">
      <div style={{padding:"28px 28px", height:"calc(100% - 54px)"}}>
        <div style={{fontFamily:MTR.mono, fontSize:12, letterSpacing:"0.22em", color:MTR.ink2, marginBottom:18}}>
          SELECT INPUT — TURN DIAL OR TAP
        </div>
        {/* Big rotary selector visualization at top */}
        <div style={{display:"grid", gridTemplateColumns:"repeat(6, 1fr)", gap:14, marginBottom:24}}>
          {SOURCES.map((s, i) => {
            const active = sel === s.id;
            return (
              <button key={s.id} onClick={()=>setSel(s.id)} style={{
                aspectRatio:"1 / 1.1",
                background: active ? MTR.ink : MTR.cream,
                color: active ? MTR.cream : MTR.ink,
                border:`1.5px solid ${MTR.ruleHi}`, cursor:"pointer", padding:"14px 12px",
                display:"flex", flexDirection:"column", justifyContent:"space-between",
                fontFamily:MTR.mono, position:"relative",
                boxShadow: active ? `4px 4px 0 ${MTR.amber}` : `2px 2px 0 ${MTR.ruleHi}`,
              }}>
                <div style={{fontSize:10, letterSpacing:"0.22em", color: active?MTR.amber:MTR.ink2}}>
                  {String(i+1).padStart(2,"0")}
                </div>
                <div style={{display:"flex", justifyContent:"center"}}>
                  <Icon name={s.icon} size={42} stroke={active?MTR.cream:MTR.ink} sw={1.6}/>
                </div>
                <div>
                  <div style={{fontSize:14, fontWeight:700, letterSpacing:"0.16em"}}>{s.label}</div>
                  <div style={{fontSize:10, color:active?MTR.cream:MTR.ink2, marginTop:2, opacity:0.8}}>{s.sub}</div>
                </div>
                {active && <div style={{position:"absolute", top:8, right:8, width:8, height:8, background:MTR.amber, borderRadius:"50%"}}/>}
              </button>
            );
          })}
        </div>

        {/* Selected detail panel */}
        <div style={{background:MTR.paper, border:`1px solid ${MTR.ruleHi}`, padding:"22px 26px", display:"grid", gridTemplateColumns:"1fr auto", gap:32, alignItems:"center"}}>
          <div>
            <div style={{fontFamily:MTR.mono, fontSize:11, letterSpacing:"0.22em", color:MTR.amber, marginBottom:6}}>● ROUTING</div>
            <div style={{fontSize:42, fontWeight:700, letterSpacing:"-0.02em", lineHeight:1}}>
              {SOURCES.find(s=>s.id===sel).label}
            </div>
            <div style={{fontSize:16, color:MTR.ink2, marginTop:8, fontFamily:MTR.mono}}>
              {SOURCES.find(s=>s.id===sel).sub} · stream → DAC pcm5122 → out
            </div>
          </div>
          <div style={{display:"flex", gap:10}}>
            <MtrButton w={120} h={92}>BACK</MtrButton>
            <MtrButton w={140} h={92} big active>CONFIRM<span style={{color:MTR.amber}}>↵</span></MtrButton>
          </div>
        </div>
      </div>
    </MtrChrome>
  );
}

// ========== VIDEO ==========
function MeterVideo() {
  const [chrome, setChrome] = React.useState(true);
  return (
    <MtrChrome label="03 · VIDEO">
      <div style={{position:"relative", height:"calc(100% - 54px)", background:"#0e0c08"}}
           onClick={()=>setChrome(!chrome)}>
        <div style={{position:"absolute", inset:0,
          background:"linear-gradient(180deg, #2a221a, #0e0c08 70%), radial-gradient(circle at 65% 35%, rgba(226,106,31,0.15), transparent 50%)"}}/>
        {/* film slate corners */}
        {[
          {top:14, left:14},{top:14, right:14},{bottom:14, left:14},{bottom:14, right:14},
        ].map((p,i)=>(
          <div key={i} style={{position:"absolute", ...p, width:18, height:18,
            borderTop: p.top!=null ? `1.5px solid ${MTR.cream}` : "none",
            borderBottom: p.bottom!=null ? `1.5px solid ${MTR.cream}` : "none",
            borderLeft: p.left!=null ? `1.5px solid ${MTR.cream}` : "none",
            borderRight: p.right!=null ? `1.5px solid ${MTR.cream}` : "none",
          }}/>
        ))}

        <div style={{position:"absolute", inset:0, display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:14, color:MTR.cream}}>
          <div style={{fontFamily:MTR.mono, fontSize:12, letterSpacing:"0.32em", opacity:0.7}}>FEATURE · 1080P · STEREO</div>
          <div style={{fontSize:72, fontWeight:700, letterSpacing:"-0.02em", textAlign:"center", lineHeight:0.95}}>
            The Royal<br/>Tenenbaums
          </div>
          <div style={{fontFamily:MTR.mono, fontSize:13, letterSpacing:"0.22em", color:MTR.amber}}>01:24:18 / 01:50:00</div>
        </div>

        {chrome && (
          <div style={{position:"absolute", left:0, right:0, bottom:0, padding:"22px 28px",
            background:`linear-gradient(0deg, rgba(15,12,8,0.88), transparent)`, color:MTR.cream, fontFamily:MTR.font}}>
            {/* Scrub */}
            <div style={{display:"flex", alignItems:"center", gap:14, marginBottom:14}}>
              <span style={{fontFamily:MTR.mono, fontSize:13, fontVariantNumeric:"tabular-nums"}}>01:24:18</span>
              <div style={{flex:1, position:"relative", height:14}}>
                <div style={{position:"absolute", left:0, right:0, top:6, height:2, background:"rgba(251,246,232,0.25)"}}/>
                <div style={{position:"absolute", left:0, top:6, height:2, width:"77%", background:MTR.amber}}/>
                {/* tick marks every 10% */}
                {Array.from({length:11}).map((_,i)=>(
                  <div key={i} style={{position:"absolute", left:`${i*10}%`, top:1, height:6, width:1, background:"rgba(251,246,232,0.4)"}}/>
                ))}
                <div style={{position:"absolute", left:"77%", top:0, width:3, height:14, background:MTR.cream}}/>
              </div>
              <span style={{fontFamily:MTR.mono, fontSize:13, fontVariantNumeric:"tabular-nums", color:MTR.amber}}>−25:42</span>
            </div>
            <div style={{display:"flex", gap:10, alignItems:"center"}}>
              <MtrButton w={92} h={76}><Icon name="back10" size={26} stroke={MTR.ink}/>−10</MtrButton>
              <MtrButton w={92} h={76}><Icon name="prev" size={26} stroke={MTR.ink}/></MtrButton>
              <MtrButton w={150} h={76} big active><Icon name="pause" size={32} stroke={MTR.cream}/>PAUSE</MtrButton>
              <MtrButton w={92} h={76}><Icon name="next" size={26} stroke={MTR.ink}/></MtrButton>
              <MtrButton w={92} h={76}><Icon name="fwd10" size={26} stroke={MTR.ink}/>+10</MtrButton>
              <span style={{flex:1}}></span>
              <MtrButton w={120} h={76}>CC · EN</MtrButton>
              <MtrButton w={120} h={76}>5.1 · DAC</MtrButton>
              <MtrButton w={92} h={76}>FULL ⛶</MtrButton>
            </div>
          </div>
        )}
      </div>
    </MtrChrome>
  );
}

Object.assign(window, { MeterAudio, MeterSource, MeterVideo });
