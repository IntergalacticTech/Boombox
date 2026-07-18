// BOOM/OS — retro desktop operating system. Beveled gray windows, pinstripe
// title bars, a menu bar with a clock, the player as overlapping "apps".
// Platinum grays + one blue selection color. Space Mono UI text.

const OS = {
  desk:"#5f7d96", win:"#d8d8d0", winHi:"#efefe8", winLo:"#8f8f86",
  ink:"#1c1c1c", ink2:"#55554e", blue:"#2a4fd0", blueHi:"#93aef0",
  stripe:"repeating-linear-gradient(0deg, #b8b8ae 0 1px, #d8d8d0 1px 3px)",
  mono:"'Space Mono', monospace", font:"'Space Mono', monospace",
};

const osBevel = { border:"2px solid", borderColor:`${OS.winHi} ${OS.winLo} ${OS.winLo} ${OS.winHi}`, background:OS.win };
const osInset = { border:"2px solid", borderColor:`${OS.winLo} ${OS.winHi} ${OS.winHi} ${OS.winLo}`, background:"#c9c9c0" };

function OsWindow({ title, children, style, active=true }) {
  return (
    <div style={{...osBevel, boxShadow:"3px 3px 0 rgba(0,0,0,0.35)", display:"flex", flexDirection:"column", ...style}}>
      <div style={{height:26, margin:3, background: active?OS.stripe:"#c9c9c0", display:"flex", alignItems:"center",
        padding:"0 6px", gap:8, flexShrink:0}}>
        <div style={{width:13, height:13, ...osBevel, borderWidth:1.5, cursor:"pointer"}}></div>
        <div style={{flex:1, textAlign:"center", fontFamily:OS.mono, fontSize:13, fontWeight:700, color:OS.ink,
          background:OS.win, padding:"0 12px", whiteSpace:"nowrap", overflow:"hidden", alignSelf:"center", lineHeight:"20px"}}>
          {title}
        </div>
        <div style={{width:13, height:13, ...osBevel, borderWidth:1.5, cursor:"pointer"}}></div>
      </div>
      <div style={{flex:1, margin:"0 3px 3px", minHeight:0, position:"relative"}}>{children}</div>
    </div>
  );
}

function OsChrome({ children, menu="Player" }) {
  const t = useTicker(500);
  return (
    <div className="ab" style={{width:1280, height:800, background:OS.desk, fontFamily:OS.mono, color:OS.ink,
      position:"relative", overflow:"hidden",
      backgroundImage:"radial-gradient(circle, rgba(255,255,255,0.06) 1px, transparent 1.5px)", backgroundSize:"5px 5px"}}>
      {/* menu bar */}
      <div style={{height:32, background:OS.win, borderBottom:`2px solid ${OS.winLo}`, display:"flex", alignItems:"center",
        padding:"0 14px", gap:22, fontSize:13, fontWeight:700}}>
        <span style={{fontSize:15}}>◉</span>
        <span style={{background:OS.ink, color:OS.win, padding:"2px 10px"}}>{menu}</span>
        <span>File</span><span>Edit</span><span>Audio</span><span>Sources</span><span>Help</span>
        <span style={{flex:1}}></span>
        <span style={{fontWeight:400, color:OS.ink2}}>DAC: pcm5122 ✓</span>
        <span>{t%2?"23:41":"23 41"}</span>
      </div>
      <div style={{position:"absolute", top:32, left:0, right:0, bottom:0}}>{children}</div>
    </div>
  );
}

function OsBtn({ children, w, h=64, primary, onClick, style }) {
  return (
    <button onClick={onClick} style={{
      width:w, height:h, ...osBevel, cursor:"pointer",
      fontFamily:OS.mono, fontSize:14, fontWeight:700, color:OS.ink,
      display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:3,
      outline: primary?`2px solid ${OS.ink}`:"none", outlineOffset:2,
      ...style,
    }}>{children}</button>
  );
}

// ========== AUDIO ==========
function OsAudio() {
  const [playing, setPlaying] = React.useState(true);
  const t = useTicker(100);
  const tr = TRACKS[0];
  return (
    <OsChrome menu="Player">
      {/* Player window */}
      <OsWindow title="⏵ Now Playing — Local Library" style={{position:"absolute", left:28, top:24, width:760, height:560}}>
        <div style={{padding:14, height:"100%", display:"flex", flexDirection:"column", gap:12}}>
          {/* track readout */}
          <div style={{...osInset, padding:"14px 18px", background:"#0e2a12", color:"#7cf59a"}}>
            <div style={{fontSize:12, opacity:0.7, letterSpacing:"0.1em"}}>TRACK 01/17 — MP3 320 — 48kHz</div>
            <div style={{fontSize:30, fontWeight:700, margin:"6px 0 2px", textShadow:"0 0 8px rgba(124,245,154,0.6)"}}>{tr.title}</div>
            <div style={{fontSize:14}}>{tr.artist} — {tr.album}</div>
            <div style={{display:"flex", justifyContent:"space-between", marginTop:10, fontSize:16, fontWeight:700}}>
              <span>01:24</span>
              <span style={{opacity:0.7}}>{Array.from({length:26}).map((_,i)=>i<15?"▓":"░").join("")}</span>
              <span>-2:24</span>
            </div>
          </div>
          {/* VU window-in-window */}
          <div style={{...osInset, padding:"10px 14px", flex:1, display:"flex", flexDirection:"column", gap:6}}>
            <div style={{fontSize:11, fontWeight:700, color:OS.ink2}}>LEVELS.CPL</div>
            {[1,2].map(s=>{
              const v = 0.4+vu(t,s)*0.5, segs=30, lit=Math.round(v*segs);
              return (
                <div key={s} style={{display:"flex", alignItems:"center", gap:8}}>
                  <span style={{fontSize:12, fontWeight:700, width:14}}>{s===1?"L":"R"}</span>
                  <div style={{flex:1, display:"flex", gap:2, height:20, ...osInset, padding:3}}>
                    {Array.from({length:segs}).map((_,i)=>(
                      <div key={i} style={{flex:1, background: i<lit ? (i>segs*0.85?"#d03a2a":i>segs*0.6?"#d0a02a":"#2a8a3a") : "#b0b0a6"}}/>
                    ))}
                  </div>
                </div>
              );
            })}
            <div style={{fontSize:11, color:OS.ink2, marginTop:2, display:"flex", justifyContent:"space-between", padding:"0 24px"}}>
              <span>−40</span><span>−20</span><span>−12</span><span>−6</span><span>0dB</span>
            </div>
          </div>
          {/* transport */}
          <div style={{display:"flex", gap:10}}>
            <OsBtn w={110} h={84}><Icon name="prev" size={26} stroke={OS.ink} sw={2.2}/>Prev</OsBtn>
            <OsBtn w={170} h={84} primary onClick={()=>setPlaying(!playing)}>
              <Icon name={playing?"pause":"play"} size={34} stroke={OS.ink} sw={2.2}/>{playing?"Pause":"Play"}
            </OsBtn>
            <OsBtn w={110} h={84}><Icon name="next" size={26} stroke={OS.ink} sw={2.2}/>Next</OsBtn>
            <OsBtn w={84} h={84}><Icon name="shuffle" size={22} stroke={OS.ink} sw={2.2}/></OsBtn>
            <OsBtn w={84} h={84}><Icon name="repeat" size={22} stroke={OS.ink} sw={2.2}/></OsBtn>
          </div>
        </div>
      </OsWindow>

      {/* Queue window (overlapping) */}
      <OsWindow title="Queue.txt" active={false} style={{position:"absolute", right:26, top:60, width:430, height:400}}>
        <div style={{padding:10, height:"100%", overflow:"hidden", background:"#fff", ...osInset, margin:0}}>
          {TRACKS.slice(0,7).map((tk,i)=>(
            <div key={i} style={{display:"flex", gap:8, padding:"8px 10px", fontSize:13,
              background:i===0?OS.blue:"transparent", color:i===0?"#fff":OS.ink}}>
              <span style={{fontWeight:700, width:22}}>{i+1}.</span>
              <span style={{flex:1, fontWeight:i===0?700:400, whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis"}}>{tk.title}</span>
              <span style={{opacity:0.7}}>{tk.time}</span>
            </div>
          ))}
        </div>
      </OsWindow>

      {/* Volume window */}
      <OsWindow title="Volume" style={{position:"absolute", right:80, bottom:36, width:360, height:150}}>
        <div style={{padding:"14px 18px", display:"flex", alignItems:"center", gap:14, height:"100%"}}>
          <Icon name="vol" size={28} stroke={OS.ink} sw={2}/>
          <div style={{flex:1, position:"relative", height:30, ...osInset}}>
            <div style={{position:"absolute", inset:3, width:"62%", background:OS.stripe}}/>
            <div style={{position:"absolute", left:"62%", top:-8, width:26, height:44, ...osBevel, cursor:"grab"}}/>
          </div>
          <span style={{fontSize:16, fontWeight:700}}>62%</span>
        </div>
      </OsWindow>
    </OsChrome>
  );
}

// ========== SOURCE ==========
function OsSource() {
  const [sel, setSel] = React.useState("local");
  return (
    <OsChrome menu="Sources">
      <OsWindow title="Sound Sources — Control Panel" style={{position:"absolute", left:80, top:36, width:1120, height:600}}>
        <div style={{padding:16, height:"100%", display:"flex", flexDirection:"column", gap:14}}>
          <div style={{fontSize:14, fontWeight:700}}>Select where sound comes from, then press OK:</div>
          <div style={{display:"grid", gridTemplateColumns:"repeat(3,1fr)", gridAutoRows:"1fr", gap:14, flex:1}}>
            {SOURCES.map((s,i)=>{
              const active = sel===s.id;
              return (
                <button key={s.id} onClick={()=>setSel(s.id)} style={{
                  ...(active?osInset:osBevel), cursor:"pointer", padding:"14px 16px",
                  fontFamily:OS.mono, textAlign:"center", color:OS.ink, position:"relative",
                  display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:8,
                  background: active?OS.blueHi:OS.win,
                }}>
                  <Icon name={s.icon} size={46} stroke={active?OS.blue:OS.ink} sw={1.9}/>
                  <span style={{fontSize:18, fontWeight:700, background:active?OS.blue:"transparent", color:active?"#fff":OS.ink, padding:"1px 8px"}}>
                    {s.label.charAt(0)+s.label.slice(1).toLowerCase()}
                  </span>
                  <span style={{fontSize:11, color:OS.ink2}}>{s.sub}</span>
                  <span style={{position:"absolute", top:8, left:10, fontSize:11, color:OS.ink2}}>{active?"◉":"○"}</span>
                </button>
              );
            })}
          </div>
          <div style={{display:"flex", gap:12, justifyContent:"flex-end", alignItems:"center"}}>
            <span style={{fontSize:12, color:OS.ink2, marginRight:"auto"}}>
              Routing: {SOURCES.find(s=>s.id===sel).label} → DAC → Speakers
            </span>
            <OsBtn w={140} h={64}>Cancel</OsBtn>
            <OsBtn w={180} h={64} primary>OK</OsBtn>
          </div>
        </div>
      </OsWindow>
    </OsChrome>
  );
}

// ========== VIDEO ==========
function OsVideo() {
  const [chrome, setChrome] = React.useState(true);
  return (
    <OsChrome menu="Movies">
      <OsWindow title="MoviePlayer — spirited_away.mp4" style={{position:"absolute", left:40, top:20, width:1200, height:700}}>
        <div onClick={()=>setChrome(!chrome)} style={{position:"relative", height:"100%", background:"#000", ...osInset, margin:0}}>
          <div style={{position:"absolute", inset:2,
            background:"radial-gradient(ellipse at 45% 40%, rgba(42,79,208,0.35), transparent 50%), radial-gradient(circle at 70% 65%, rgba(147,174,240,0.2), transparent 45%), linear-gradient(180deg,#0a1030,#000)"}}/>
          <div style={{position:"absolute", inset:0, display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:12, color:"#e8ecf8"}}>
            <div style={{fontSize:12, letterSpacing:"0.3em", opacity:0.7}}>MOVIEPLAYER 1.1 · 1080P</div>
            <div style={{fontSize:66, fontWeight:700, letterSpacing:"-0.02em", textAlign:"center", lineHeight:1}}>Spirited Away</div>
            <div style={{fontSize:14, opacity:0.7}}>01:04:18 / 02:05:00</div>
          </div>
          {chrome && (
            <div style={{position:"absolute", left:10, right:10, bottom:10, ...osBevel, padding:"10px 14px"}}>
              <div style={{display:"flex", alignItems:"center", gap:12, marginBottom:10, fontSize:13, fontWeight:700}}>
                <span>01:04:18</span>
                <div style={{flex:1, position:"relative", height:22, ...osInset}}>
                  <div style={{position:"absolute", inset:3, width:"51%", background:OS.stripe}}/>
                  <div style={{position:"absolute", left:"51%", top:-6, width:22, height:34, ...osBevel, cursor:"grab"}}/>
                </div>
                <span>−1:00:42</span>
              </div>
              <div style={{display:"flex", gap:8}}>
                <OsBtn w={88} h={64}>−10s</OsBtn>
                <OsBtn w={88} h={64}><Icon name="prev" size={22} stroke={OS.ink} sw={2.2}/></OsBtn>
                <OsBtn w={140} h={64} primary><Icon name="pause" size={26} stroke={OS.ink} sw={2.2}/>Pause</OsBtn>
                <OsBtn w={88} h={64}><Icon name="next" size={22} stroke={OS.ink} sw={2.2}/></OsBtn>
                <OsBtn w={88} h={64}>+10s</OsBtn>
                <span style={{flex:1}}></span>
                <OsBtn w={110} h={64}>Subs</OsBtn>
                <OsBtn w={110} h={64}>Audio</OsBtn>
                <OsBtn w={88} h={64}>⛶</OsBtn>
              </div>
            </div>
          )}
        </div>
      </OsWindow>
    </OsChrome>
  );
}

Object.assign(window, { OsAudio, OsSource, OsVideo });
