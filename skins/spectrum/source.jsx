// SPECTRUM — visualizer-first immersive. Track info overlays the field.
// Color: deep ink + cyan/violet + safety amber. Big chunky transport in a
// translucent glass tray that auto-hides on Now Playing.

const SPC = {
  bg:       "#070a14",
  ink:      "#e9ecf2",
  ink2:     "#8a93b0",
  glass:    "rgba(255,255,255,0.06)",
  glassHi:  "rgba(255,255,255,0.12)",
  rule:     "rgba(255,255,255,0.12)",
  cyan:     "#5be7ff",
  violet:   "#b794ff",
  amber:    "#ffb84d",
  red:      "#ff5466",
  font:     "'Space Grotesk', system-ui, -apple-system, sans-serif",
  mono:     "'JetBrains Mono', monospace",
};

function SpcChrome({ children }) {
  return (
    <div className="ab" style={{
      width:1280, height:800, background:SPC.bg, color:SPC.ink, fontFamily:SPC.font,
      position:"relative", overflow:"hidden",
    }}>{children}</div>
  );
}

function SpcBtn({ children, w, h=92, big, active, primary, onClick }) {
  return (
    <button onClick={onClick} style={{
      width: w || (big ? 180 : 110),
      height: big ? 120 : h,
      background: primary ? SPC.ink : (active ? SPC.glassHi : SPC.glass),
      color: primary ? SPC.bg : SPC.ink,
      backdropFilter:"blur(20px)",
      border:`1px solid ${primary ? SPC.ink : SPC.rule}`,
      borderRadius: big ? 24 : 18,
      cursor:"pointer",
      fontFamily:SPC.font, fontSize: big?15:13, fontWeight:600, letterSpacing:"0.14em", textTransform:"uppercase",
      display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:4,
      transition:"all .12s",
    }}>{children}</button>
  );
}

// Radial spectrum visual — bars rotate around a center dot.
function RadialSpectrum({ size = 560 }) {
  const t = useTicker(60);
  const N = 96;
  return (
    <svg width={size} height={size} viewBox={`-${size/2} -${size/2} ${size} ${size}`} style={{display:"block"}}>
      <defs>
        <radialGradient id="spcGlow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor={SPC.cyan} stopOpacity="0.25"/>
          <stop offset="60%" stopColor={SPC.violet} stopOpacity="0.08"/>
          <stop offset="100%" stopColor="transparent"/>
        </radialGradient>
      </defs>
      <circle cx="0" cy="0" r={size*0.42} fill="url(#spcGlow)"/>
      {/* concentric rings */}
      {[0.30, 0.36, 0.46].map((r, i) => (
        <circle key={i} cx="0" cy="0" r={size*r} fill="none" stroke={SPC.rule} strokeWidth="0.8" strokeDasharray={i===2?"2 4":""}/>
      ))}
      {/* bars */}
      {Array.from({length:N}).map((_, i) => {
        const a = (i / N) * Math.PI * 2;
        const v = vu(t * 0.7, i * 0.4 + 1);
        const r1 = size * 0.32;
        const r2 = r1 + v * (size * 0.12);
        const x1 = Math.cos(a) * r1, y1 = Math.sin(a) * r1;
        const x2 = Math.cos(a) * r2, y2 = Math.sin(a) * r2;
        const hue = (i * 7 + t) % 360;
        const hot = v > 0.85;
        return (
          <line key={i} x1={x1} y1={y1} x2={x2} y2={y2}
            stroke={hot ? SPC.amber : (i%4===0 ? SPC.cyan : SPC.violet)}
            strokeOpacity={0.55 + v*0.45}
            strokeWidth={2.2} strokeLinecap="round"/>
        );
      })}
      {/* outer arc fragments */}
      {[0,1,2,3].map(i=>{
        const a = i * 90 + (t * 0.4 % 360);
        const r = size * 0.46;
        return <path key={i} d={`M ${Math.cos(a*Math.PI/180)*r} ${Math.sin(a*Math.PI/180)*r} A ${r} ${r} 0 0 1 ${Math.cos((a+24)*Math.PI/180)*r} ${Math.sin((a+24)*Math.PI/180)*r}`}
          fill="none" stroke={SPC.cyan} strokeWidth="1.5" strokeOpacity="0.7"/>;
      })}
      {/* center */}
      <circle cx="0" cy="0" r="3" fill={SPC.amber}/>
    </svg>
  );
}

// Linear waveform strip
function WaveStrip({ width=1232, height=60 }) {
  const t = useTicker(80);
  const N = 220;
  return (
    <svg width="100%" viewBox={`0 -${height/2} ${N} ${height}`} preserveAspectRatio="none" style={{height, display:"block"}}>
      {Array.from({length:N}).map((_,i)=>{
        const v = vu(t*0.5, i*0.18) * 0.9 + 0.1;
        return <line key={i} x1={i+0.5} x2={i+0.5} y1={-v*height/2} y2={v*height/2}
          stroke={i % 12 === 0 ? SPC.amber : SPC.cyan} strokeOpacity={0.6 + v*0.4} strokeWidth="0.8"/>;
      })}
    </svg>
  );
}

// ========== AUDIO ==========
function SpectrumAudio() {
  const [playing, setPlaying] = React.useState(true);
  const tr = TRACKS[3];
  return (
    <SpcChrome>
      {/* Background ambient gradients */}
      <div style={{position:"absolute", inset:0,
        background:`radial-gradient(circle at 30% 30%, rgba(91,231,255,0.15), transparent 50%),
                    radial-gradient(circle at 70% 70%, rgba(183,148,255,0.18), transparent 55%),
                    linear-gradient(180deg, #07091a 0%, #050714 100%)`}}/>
      {/* status pill row */}
      <div style={{position:"absolute", top:24, left:28, right:28, display:"flex", alignItems:"center", gap:14, fontFamily:SPC.mono, fontSize:12, letterSpacing:"0.22em", textTransform:"uppercase"}}>
        <div style={{padding:"6px 12px", background:SPC.glass, border:`1px solid ${SPC.rule}`, borderRadius:999, backdropFilter:"blur(12px)"}}>
          <span style={{color:SPC.amber}}>●</span> Now Playing · Local
        </div>
        <div style={{padding:"6px 12px", background:SPC.glass, border:`1px solid ${SPC.rule}`, borderRadius:999, backdropFilter:"blur(12px)", color:SPC.ink2}}>
          DAC pcm5122 · 48k · 24bit
        </div>
        <div style={{flex:1}}></div>
        <div style={{padding:"6px 12px", background:SPC.glass, border:`1px solid ${SPC.rule}`, borderRadius:999, backdropFilter:"blur(12px)", color:SPC.ink2}}>
          ⌗ 04 / 17
        </div>
        <div style={{padding:"6px 12px", background:SPC.glass, border:`1px solid ${SPC.rule}`, borderRadius:999, backdropFilter:"blur(12px)", color:SPC.ink2}}>
          23:41
        </div>
      </div>

      {/* Centered radial vis with title overlay */}
      <div style={{position:"absolute", top:80, left:0, right:0, display:"flex", justifyContent:"center"}}>
        <div style={{position:"relative", width:560, height:560}}>
          <RadialSpectrum size={560}/>
          {/* center title block */}
          <div style={{position:"absolute", inset:0, display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", textAlign:"center", gap:6, pointerEvents:"none"}}>
            <div style={{fontFamily:SPC.mono, fontSize:11, letterSpacing:"0.32em", textTransform:"uppercase", color:SPC.cyan}}>Track 04</div>
            <div style={{fontFamily:SPC.font, fontWeight:700, fontSize:46, lineHeight:1.02, letterSpacing:"-0.02em", maxWidth:340}}>
              {tr.title}
            </div>
            <div style={{fontFamily:SPC.font, fontSize:18, color:SPC.ink2, marginTop:4}}>{tr.artist}</div>
            <div style={{fontFamily:SPC.mono, fontSize:11, color:SPC.ink2, marginTop:2, letterSpacing:"0.18em"}}>{tr.album.toUpperCase()}</div>
          </div>
        </div>
      </div>

      {/* Bottom glass tray: waveform + transport */}
      <div style={{position:"absolute", left:24, right:24, bottom:24,
        background:"rgba(8,12,28,0.55)", backdropFilter:"blur(28px)",
        border:`1px solid ${SPC.rule}`, borderRadius:28, padding:"18px 22px",
        boxShadow:"0 24px 60px rgba(0,0,0,0.45)"}}>
        {/* waveform with playhead */}
        <div style={{position:"relative", height:60, marginBottom:14}}>
          <WaveStrip />
          <div style={{position:"absolute", left:"56%", top:-4, bottom:-4, width:2, background:SPC.amber, boxShadow:`0 0 12px ${SPC.amber}`}}/>
        </div>
        <div style={{display:"flex", alignItems:"center", gap:14}}>
          <div style={{fontFamily:SPC.mono, fontSize:13, fontVariantNumeric:"tabular-nums", letterSpacing:"0.08em", width:80}}>
            <div style={{color:SPC.amber}}>04:21</div>
            <div style={{color:SPC.ink2, fontSize:11}}>/ 07:47</div>
          </div>
          <div style={{flex:1}}></div>
          <SpcBtn><Icon name="shuffle" size={22}/></SpcBtn>
          <SpcBtn w={100}><Icon name="prev" size={26}/></SpcBtn>
          <SpcBtn big primary onClick={()=>setPlaying(!playing)}>
            <Icon name={playing?"pause":"play"} size={40} stroke={SPC.bg}/>
          </SpcBtn>
          <SpcBtn w={100}><Icon name="next" size={26}/></SpcBtn>
          <SpcBtn><Icon name="repeat" size={22}/></SpcBtn>
          <div style={{flex:1}}></div>
          <div style={{display:"flex", alignItems:"center", gap:10, padding:"10px 16px", background:SPC.glass, border:`1px solid ${SPC.rule}`, borderRadius:18, width:200}}>
            <Icon name="vol" size={22}/>
            <div style={{flex:1, height:4, background:"rgba(255,255,255,0.18)", borderRadius:2, position:"relative"}}>
              <div style={{height:"100%", width:"62%", background:SPC.cyan, borderRadius:2}}/>
              <div style={{position:"absolute", left:"62%", top:-6, width:14, height:14, borderRadius:"50%", background:SPC.ink, border:`2px solid ${SPC.bg}`, transform:"translateX(-50%)"}}/>
            </div>
          </div>
        </div>
      </div>
    </SpcChrome>
  );
}

// ========== SOURCE ==========
function SpectrumSource() {
  const [sel, setSel] = React.useState("local");
  return (
    <SpcChrome>
      <div style={{position:"absolute", inset:0,
        background:`radial-gradient(circle at 50% 0%, rgba(91,231,255,0.15), transparent 50%),
                    linear-gradient(180deg, #07091a 0%, #050714 100%)`}}/>
      <div style={{padding:"40px 44px", height:"100%", display:"flex", flexDirection:"column"}}>
        <div style={{display:"flex", alignItems:"baseline", gap:18, marginBottom:8}}>
          <div style={{fontFamily:SPC.mono, fontSize:12, letterSpacing:"0.32em", textTransform:"uppercase", color:SPC.cyan}}>02 · ROUTE</div>
          <div style={{fontFamily:SPC.mono, fontSize:12, letterSpacing:"0.22em", color:SPC.ink2}}>where do you want sound to come from?</div>
        </div>
        <div style={{fontFamily:SPC.font, fontSize:64, fontWeight:600, letterSpacing:"-0.03em", lineHeight:1, marginBottom:30}}>
          Pick a source.
        </div>

        <div style={{display:"grid", gridTemplateColumns:"repeat(3, 1fr)", gridAutoRows:"1fr", gap:18, flex:1}}>
          {SOURCES.map((s, i) => {
            const active = sel === s.id;
            return (
              <button key={s.id} onClick={()=>setSel(s.id)} style={{
                background: active ? "rgba(91,231,255,0.10)" : SPC.glass,
                backdropFilter:"blur(18px)",
                border:`1px solid ${active ? SPC.cyan : SPC.rule}`,
                borderRadius:24, padding:"24px 26px", textAlign:"left", cursor:"pointer", color:SPC.ink,
                position:"relative", overflow:"hidden",
                boxShadow: active ? `0 0 60px rgba(91,231,255,0.18)` : "none",
                transition:"all .15s",
                display:"flex", flexDirection:"column", justifyContent:"space-between", gap:12,
              }}>
                {/* corner halo for active */}
                {active && <div style={{position:"absolute", top:-40, right:-40, width:160, height:160,
                  background:`radial-gradient(circle, ${SPC.cyan}, transparent 70%)`, opacity:0.25}}/>}
                <div style={{display:"flex", justifyContent:"space-between", alignItems:"flex-start", position:"relative"}}>
                  <Icon name={s.icon} size={44} stroke={active ? SPC.cyan : SPC.ink} sw={1.5}/>
                  <div style={{display:"flex", alignItems:"center", gap:6, fontFamily:SPC.mono, fontSize:11, letterSpacing:"0.22em",
                    color: active ? SPC.amber : SPC.ink2}}>
                    {active ? "● ACTIVE" : "○ READY"}
                  </div>
                </div>
                <div style={{position:"relative"}}>
                  <div style={{fontFamily:SPC.font, fontSize:32, fontWeight:600, letterSpacing:"-0.02em"}}>{s.label.charAt(0) + s.label.slice(1).toLowerCase()}</div>
                  <div style={{fontFamily:SPC.mono, fontSize:13, color:SPC.ink2, marginTop:6, letterSpacing:"0.04em"}}>{s.sub}</div>
                </div>
                {/* mini level when active */}
                {active && (
                  <div style={{display:"flex", gap:2, alignItems:"flex-end", height:20}}>
                    {Array.from({length:32}).map((_,j)=>(
                      <div key={j} style={{flex:1, height: `${20 + Math.sin(j*0.7)*40 + Math.cos(j*0.3)*30}%`,
                        background: j%4===0 ? SPC.amber : SPC.cyan, opacity:0.7}}/>
                    ))}
                  </div>
                )}
              </button>
            );
          })}
        </div>
      </div>
    </SpcChrome>
  );
}

// ========== VIDEO ==========
function SpectrumVideo() {
  const [chrome, setChrome] = React.useState(true);
  return (
    <SpcChrome>
      <div onClick={()=>setChrome(!chrome)} style={{position:"absolute", inset:0, background:"#000"}}>
        {/* fake video field */}
        <div style={{position:"absolute", inset:0,
          background:`radial-gradient(ellipse at 40% 50%, rgba(255,184,77,0.25), transparent 40%),
                      radial-gradient(circle at 70% 70%, rgba(91,231,255,0.18), transparent 40%),
                      linear-gradient(180deg, #2a1808, #000 80%)`}}/>
        <div style={{position:"absolute", inset:0, display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:12, color:SPC.ink}}>
          <div style={{fontFamily:SPC.mono, fontSize:12, letterSpacing:"0.32em", textTransform:"uppercase", color:SPC.amber}}>FILM · 4K · DOLBY</div>
          <div style={{fontFamily:SPC.font, fontSize:80, fontWeight:700, letterSpacing:"-0.03em"}}>2001</div>
          <div style={{fontFamily:SPC.font, fontSize:32, color:SPC.ink2}}>A Space Odyssey</div>
        </div>

        {chrome && (
          <>
            <div style={{position:"absolute", top:24, left:28, right:28, display:"flex", alignItems:"center", gap:12, fontFamily:SPC.mono, fontSize:12, letterSpacing:"0.22em", textTransform:"uppercase", color:SPC.ink}}>
              <div style={{padding:"6px 12px", background:SPC.glass, border:`1px solid ${SPC.rule}`, borderRadius:999, backdropFilter:"blur(12px)"}}>
                <Icon name="back" size={14} stroke={SPC.ink}/> Library
              </div>
              <div style={{flex:1}}></div>
              <div style={{padding:"6px 12px", background:"rgba(255,184,77,0.15)", border:`1px solid ${SPC.amber}`, color:SPC.amber, borderRadius:999, backdropFilter:"blur(12px)"}}>
                CASTING · LIVING ROOM TV
              </div>
            </div>

            <div style={{position:"absolute", left:24, right:24, bottom:24,
              background:"rgba(8,12,28,0.55)", backdropFilter:"blur(28px)",
              border:`1px solid ${SPC.rule}`, borderRadius:24, padding:"16px 20px"}}>
              {/* scrubber */}
              <div style={{display:"flex", alignItems:"center", gap:14, marginBottom:14}}>
                <span style={{fontFamily:SPC.mono, fontSize:13, fontVariantNumeric:"tabular-nums", color:SPC.amber}}>01:24:18</span>
                <div style={{flex:1, height:4, background:"rgba(255,255,255,0.18)", borderRadius:2, position:"relative"}}>
                  <div style={{height:"100%", width:"56%", background:SPC.cyan, borderRadius:2}}/>
                  <div style={{position:"absolute", left:"56%", top:-7, width:18, height:18, borderRadius:"50%", background:SPC.ink, border:`2px solid ${SPC.bg}`, transform:"translateX(-50%)"}}/>
                </div>
                <span style={{fontFamily:SPC.mono, fontSize:13, fontVariantNumeric:"tabular-nums", color:SPC.ink2}}>02:43:51</span>
              </div>
              <div style={{display:"flex", gap:10, alignItems:"center"}}>
                <SpcBtn w={92}><Icon name="back10" size={24}/></SpcBtn>
                <SpcBtn w={92}><Icon name="prev" size={24}/></SpcBtn>
                <SpcBtn big primary><Icon name="pause" size={36} stroke={SPC.bg}/></SpcBtn>
                <SpcBtn w={92}><Icon name="next" size={24}/></SpcBtn>
                <SpcBtn w={92}><Icon name="fwd10" size={24}/></SpcBtn>
                <div style={{flex:1}}></div>
                <SpcBtn w={120}>CC · EN</SpcBtn>
                <SpcBtn w={120}>5.1 · DAC</SpcBtn>
                <SpcBtn w={92}>⛶</SpcBtn>
              </div>
            </div>
          </>
        )}
      </div>
    </SpcChrome>
  );
}

Object.assign(window, { SpectrumAudio, SpectrumSource, SpectrumVideo });
