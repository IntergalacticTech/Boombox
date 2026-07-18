// MIDNIGHT FM — the tuner-dial metaphor. A giant horizontal frequency scale is
// the core navigation: tracks/sources sit at "frequencies" and a red needle marks
// the current one. Warm charcoal, cream, oxide red. Space Grotesk + Space Mono.

const FM = {
  bg:"#191512", panel:"#221d18", panelHi:"#2c261f",
  cream:"#f0e7d8", cream2:"#a89a85", cream3:"#655a4b",
  red:"#e5482e", gold:"#d9a441", teal:"#78b7a8",
  rule:"rgba(240,231,216,0.10)", ruleHi:"rgba(240,231,216,0.22)",
  font:"'Space Grotesk', sans-serif", mono:"'Space Mono', monospace",
};

function FmChrome({ children, band="A" }) {
  return (
    <div className="ab" style={{width:1280, height:800, background:FM.bg, color:FM.cream, fontFamily:FM.font, position:"relative", overflow:"hidden"}}>
      <div style={{height:50, padding:"0 26px", display:"flex", alignItems:"center", gap:18, borderBottom:`1px solid ${FM.rule}`,
        fontFamily:FM.mono, fontSize:12, letterSpacing:"0.2em"}}>
        <span style={{fontSize:16, fontWeight:700, letterSpacing:"0.3em", color:FM.cream}}>MIDNIGHT FM</span>
        <span style={{color:FM.cream3}}>·</span>
        <span style={{color:FM.gold}}>BAND {band}</span>
        <span style={{flex:1}}></span>
        <span style={{color:FM.teal}}>STEREO ◉◉</span>
        <span style={{color:FM.cream3}}>·</span>
        <span style={{color:FM.cream2}}>SIG ▂▄▆█</span>
        <span style={{color:FM.cream3}}>·</span>
        <span>23:41</span>
      </div>
      {children}
    </div>
  );
}

// The big dial: horizontal scale with numbered stops, needle at active position.
function FmDial({ stops, active, height=150, onPick }) {
  const n = stops.length;
  const pos = i => 8 + (i/(n-1)) * 84; // percent across
  return (
    <div style={{position:"relative", height, background:FM.panel, border:`1px solid ${FM.rule}`, borderRadius:8, overflow:"hidden"}}>
      {/* fine ticks */}
      {Array.from({length:97}).map((_,i)=>(
        <div key={i} style={{position:"absolute", left:`${2+i*1}%`, bottom:18, width:1,
          height: i%8===0?34:i%4===0?22:12, background: i%8===0?FM.cream2:FM.cream3, opacity:0.7}}/>
      ))}
      {/* numbered stops */}
      {stops.map((s,i)=>(
        <button key={i} onClick={()=>onPick && onPick(i)} style={{
          position:"absolute", left:`${pos(i)}%`, top:10, transform:"translateX(-50%)",
          background:"none", border:"none", cursor:"pointer", textAlign:"center",
          color: i===active?FM.cream:FM.cream3, fontFamily:FM.mono, padding:"6px 10px",
        }}>
          <div style={{fontSize:22, fontWeight:700, letterSpacing:"0.04em"}}>{s.freq}</div>
          <div style={{fontSize:10, letterSpacing:"0.16em", marginTop:2, maxWidth:110, overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap"}}>{s.label}</div>
        </button>
      ))}
      {/* needle */}
      <div style={{position:"absolute", left:`${pos(active)}%`, top:0, bottom:0, width:3, background:FM.red,
        boxShadow:`0 0 14px ${FM.red}`, transition:"left .4s cubic-bezier(.3,1.2,.4,1)"}}/>
      <div style={{position:"absolute", left:`${pos(active)}%`, bottom:0, transform:"translateX(-50%)",
        width:0, height:0, borderLeft:"7px solid transparent", borderRight:"7px solid transparent",
        borderBottom:`8px solid ${FM.red}`, transition:"left .4s cubic-bezier(.3,1.2,.4,1)"}}/>
    </div>
  );
}

function FmBtn({ children, w, h=88, primary, onClick }) {
  return (
    <button onClick={onClick} style={{
      width:w, height:h, background:primary?FM.red:FM.panelHi, color:primary?FM.cream:FM.cream2,
      border:`1px solid ${primary?FM.red:FM.ruleHi}`, borderRadius:10, cursor:"pointer",
      fontFamily:FM.mono, fontSize:13, fontWeight:700, letterSpacing:"0.16em",
      display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:5,
      boxShadow:primary?`0 6px 24px ${FM.red}55`:"0 3px 0 rgba(0,0,0,0.35)", transition:"all .1s",
    }}>{children}</button>
  );
}

// ========== AUDIO ==========
function FmAudio() {
  const [idx, setIdx] = React.useState(2);
  const [playing, setPlaying] = React.useState(true);
  const t = useTicker(80);
  const tr = TRACKS[idx];
  const stops = TRACKS.slice(0,7).map((tk,i)=>({freq:(88.1+i*2.2).toFixed(1), label:tk.title}));
  return (
    <FmChrome band="A · LOCAL">
      <div style={{padding:"24px 26px", height:"calc(100% - 50px)", display:"flex", flexDirection:"column", gap:18}}>
        {/* Hero: now playing */}
        <div style={{display:"flex", alignItems:"flex-end", justifyContent:"space-between", gap:24}}>
          <div>
            <div style={{fontFamily:FM.mono, fontSize:12, color:FM.red, letterSpacing:"0.3em", marginBottom:10}}>
              ● TUNED · {stops[idx].freq} · TRACK {String(idx+1).padStart(2,"0")}
            </div>
            <div style={{fontSize:58, fontWeight:700, letterSpacing:"-0.03em", lineHeight:0.95}}>{tr.title}</div>
            <div style={{fontSize:19, color:FM.cream2, marginTop:10}}>
              {tr.artist} <span style={{color:FM.cream3}}>—</span> <em>{tr.album}</em>
            </div>
          </div>
          <div style={{textAlign:"right", fontFamily:FM.mono, flexShrink:0}}>
            <div style={{fontSize:60, fontWeight:700, color:FM.gold, lineHeight:1, fontVariantNumeric:"tabular-nums"}}>{mmss(96)}</div>
            <div style={{fontSize:13, color:FM.cream3, marginTop:6, letterSpacing:"0.14em"}}>OF {tr.time}</div>
          </div>
        </div>

        {/* Signal strip (progress) */}
        <div style={{display:"flex", alignItems:"center", gap:14}}>
          <span style={{fontFamily:FM.mono, fontSize:11, color:FM.cream3, letterSpacing:"0.2em"}}>POS</span>
          <div style={{flex:1, height:34, background:FM.panel, border:`1px solid ${FM.rule}`, borderRadius:6, position:"relative", overflow:"hidden", display:"flex", alignItems:"center", gap:2, padding:"0 4px"}}>
            {Array.from({length:90}).map((_,i)=>{
              const played = i < 38;
              const v = vu(t*0.4, i*0.3);
              return <div key={i} style={{flex:1, height:`${20+v*65}%`, background: played?FM.gold:FM.cream3, opacity:played?0.95:0.35, borderRadius:1}}/>;
            })}
            <div style={{position:"absolute", left:"42.5%", top:0, bottom:0, width:2, background:FM.red, boxShadow:`0 0 10px ${FM.red}`}}/>
          </div>
          <span style={{fontFamily:FM.mono, fontSize:11, color:FM.cream2, fontVariantNumeric:"tabular-nums"}}>−{mmss(tr.len-96)}</span>
        </div>

        {/* THE DIAL — queue as stations */}
        <div>
          <div style={{fontFamily:FM.mono, fontSize:11, color:FM.cream3, letterSpacing:"0.26em", marginBottom:8, display:"flex", justifyContent:"space-between"}}>
            <span>QUEUE DIAL — TAP A STATION OR SPIN</span><span style={{color:FM.gold}}>7 TRACKS</span>
          </div>
          <FmDial stops={stops} active={idx} onPick={setIdx}/>
        </div>

        {/* Transport */}
        <div style={{display:"flex", gap:12, alignItems:"center", marginTop:"auto"}}>
          <FmBtn w={130} onClick={()=>setIdx(Math.max(0,idx-1))}><Icon name="prev" size={26} stroke="currentColor"/>TUNE ◀</FmBtn>
          <FmBtn w={190} primary onClick={()=>setPlaying(!playing)}>
            <Icon name={playing?"pause":"play"} size={34} stroke={FM.cream}/>{playing?"PAUSE":"PLAY"}
          </FmBtn>
          <FmBtn w={130} onClick={()=>setIdx(Math.min(stops.length-1,idx+1))}>TUNE ▶<Icon name="next" size={26} stroke="currentColor"/></FmBtn>
          <FmBtn w={96}><Icon name="shuffle" size={22} stroke="currentColor"/></FmBtn>
          <FmBtn w={96}><Icon name="repeat" size={22} stroke="currentColor"/></FmBtn>
          <span style={{flex:1}}></span>
          <div style={{width:280, background:FM.panel, border:`1px solid ${FM.rule}`, borderRadius:10, padding:"12px 16px", height:88, display:"flex", flexDirection:"column", justifyContent:"center", gap:8}}>
            <div style={{display:"flex", justifyContent:"space-between", fontFamily:FM.mono, fontSize:11, letterSpacing:"0.2em", color:FM.cream3}}>
              <span>VOLUME</span><span style={{color:FM.gold}}>62</span>
            </div>
            <div style={{height:10, background:"rgba(0,0,0,0.45)", borderRadius:5, position:"relative"}}>
              <div style={{height:"100%", width:"62%", background:FM.gold, borderRadius:5}}/>
              <div style={{position:"absolute", left:"62%", top:-5, width:20, height:20, borderRadius:"50%", background:FM.cream, border:`3px solid ${FM.bg}`, transform:"translateX(-50%)"}}/>
            </div>
          </div>
        </div>
      </div>
    </FmChrome>
  );
}

// ========== SOURCE ==========
function FmSource() {
  const [sel, setSel] = React.useState(0);
  const stops = SOURCES.map((s,i)=>({freq:["88.1","92.5","96.9","101.3","105.7","107.9"][i], label:s.label}));
  const s = SOURCES[sel];
  return (
    <FmChrome band="SELECT">
      <div style={{padding:"28px 26px", height:"calc(100% - 50px)", display:"flex", flexDirection:"column", gap:20}}>
        <div>
          <div style={{fontFamily:FM.mono, fontSize:12, color:FM.red, letterSpacing:"0.3em", marginBottom:10}}>● INPUT DIAL</div>
          <div style={{fontSize:50, fontWeight:700, letterSpacing:"-0.03em", lineHeight:1}}>Tune to a source.</div>
        </div>

        <FmDial stops={stops} active={sel} onPick={setSel} height={170}/>

        {/* Selected station card */}
        <div style={{flex:1, background:FM.panel, border:`1px solid ${FM.rule}`, borderRadius:12, padding:"26px 30px",
          display:"grid", gridTemplateColumns:"auto 1fr auto", gap:28, alignItems:"center"}}>
          <div style={{width:110, height:110, borderRadius:16, background:FM.panelHi, border:`1px solid ${FM.ruleHi}`,
            display:"flex", alignItems:"center", justifyContent:"center"}}>
            <Icon name={s.icon} size={54} stroke={FM.gold} sw={1.6}/>
          </div>
          <div>
            <div style={{fontFamily:FM.mono, fontSize:26, color:FM.gold, fontWeight:700}}>{stops[sel].freq} <span style={{fontSize:14, color:FM.cream3}}>MHz</span></div>
            <div style={{fontSize:40, fontWeight:700, letterSpacing:"-0.02em", lineHeight:1.05}}>{s.label.charAt(0)+s.label.slice(1).toLowerCase()}</div>
            <div style={{fontFamily:FM.mono, fontSize:14, color:FM.cream2, marginTop:8}}>{s.sub} · signal strong · ready to route</div>
          </div>
          <div style={{display:"flex", flexDirection:"column", gap:10}}>
            <FmBtn w={190} h={76} primary>LOCK IN ↵</FmBtn>
            <FmBtn w={190} h={64}>SCAN NEXT</FmBtn>
          </div>
        </div>
      </div>
    </FmChrome>
  );
}

// ========== VIDEO ==========
function FmVideo() {
  const [chrome, setChrome] = React.useState(true);
  return (
    <FmChrome band="V · CAST">
      <div onClick={()=>setChrome(!chrome)} style={{position:"relative", height:"calc(100% - 50px)", background:"#000"}}>
        <div style={{position:"absolute", inset:0,
          background:"radial-gradient(ellipse at 40% 50%, rgba(229,72,46,0.22), transparent 50%), radial-gradient(circle at 72% 40%, rgba(217,164,65,0.15), transparent 45%), linear-gradient(180deg,#1c0f08,#000 80%)"}}/>
        <div style={{position:"absolute", inset:0, display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:14}}>
          <div style={{fontFamily:FM.mono, fontSize:12, letterSpacing:"0.32em", color:FM.gold}}>LATE FEATURE · 1080P</div>
          <div style={{fontSize:82, fontWeight:700, letterSpacing:"-0.03em", lineHeight:0.92, textAlign:"center"}}>Drive</div>
          <div style={{fontFamily:FM.mono, fontSize:14, letterSpacing:"0.22em", color:FM.cream2}}>01:04:18 / 01:40:00</div>
        </div>
        {chrome && (
          <>
            <div style={{position:"absolute", top:16, left:24, right:24, display:"flex", gap:12, alignItems:"center", fontFamily:FM.mono, fontSize:12, letterSpacing:"0.2em"}}>
              <span style={{padding:"7px 14px", background:FM.panel, border:`1px solid ${FM.ruleHi}`, borderRadius:999}}>◀ BACK</span>
              <span style={{flex:1}}></span>
              <span style={{padding:"7px 14px", background:"rgba(229,72,46,0.16)", border:`1px solid ${FM.red}`, color:FM.red, borderRadius:999}}>● CASTING · LIVING ROOM</span>
            </div>
            <div style={{position:"absolute", left:24, right:24, bottom:20, background:"rgba(34,29,24,0.85)", backdropFilter:"blur(16px)",
              border:`1px solid ${FM.ruleHi}`, borderRadius:14, padding:"16px 22px"}}>
              {/* dial-style scrubber */}
              <div style={{position:"relative", height:40, marginBottom:12, overflow:"hidden"}}>
                {Array.from({length:80}).map((_,i)=>(
                  <div key={i} style={{position:"absolute", left:`${1+i*1.25}%`, bottom:4, width:1,
                    height:i%10===0?26:i%5===0?17:9, background:i<52?FM.gold:FM.cream3, opacity:i<52?0.9:0.4}}/>
                ))}
                <div style={{position:"absolute", left:"64%", top:0, bottom:0, width:3, background:FM.red, boxShadow:`0 0 12px ${FM.red}`}}/>
              </div>
              <div style={{display:"flex", gap:10, alignItems:"center"}}>
                <span style={{fontFamily:FM.mono, fontSize:13, color:FM.gold, width:76, fontVariantNumeric:"tabular-nums"}}>01:04:18</span>
                <FmBtn w={96} h={72}><Icon name="back10" size={24} stroke="currentColor"/></FmBtn>
                <FmBtn w={96} h={72}><Icon name="prev" size={24} stroke="currentColor"/></FmBtn>
                <FmBtn w={160} h={72} primary><Icon name="pause" size={30} stroke={FM.cream}/>PAUSE</FmBtn>
                <FmBtn w={96} h={72}><Icon name="next" size={24} stroke="currentColor"/></FmBtn>
                <FmBtn w={96} h={72}><Icon name="fwd10" size={24} stroke="currentColor"/></FmBtn>
                <span style={{flex:1}}></span>
                <FmBtn w={110} h={72}>CC EN</FmBtn>
                <FmBtn w={110} h={72}>5.1</FmBtn>
              </div>
            </div>
          </>
        )}
      </div>
    </FmChrome>
  );
}

Object.assign(window, { FmAudio, FmSource, FmVideo });
