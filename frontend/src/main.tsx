import React, {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {BrowserRouter, Link, NavLink, Route, Routes} from 'react-router-dom';
import './styles.css';

const base = import.meta.env.VITE_API_BASE_URL as string;
// All appointment times are shown in the clinic's timezone so the assistant
// and the appointments page always agree, regardless of the viewer's device.
const CLINIC_TIMEZONE = (import.meta.env.VITE_CLINIC_TIMEZONE as string) || 'Asia/Riyadh';
const dtFormat = new Intl.DateTimeFormat(undefined, {dateStyle:'medium', timeStyle:'short', timeZone: CLINIC_TIMEZONE});
function fmtDateTime(iso: string){try{return dtFormat.format(new Date(iso))}catch{return iso}}

// ---------- auth state (localStorage-backed) ----------
type Auth = {token: string, patient: {patient_reference: string, email: string, display_name?: string | null}};
const AUTH_KEY = 'carepath_auth';
function loadAuth(): Auth | null {try{const raw = localStorage.getItem(AUTH_KEY);return raw ? JSON.parse(raw) as Auth : null}catch{return null}}
function saveAuth(auth: Auth | null) {if (auth) localStorage.setItem(AUTH_KEY, JSON.stringify(auth)); else localStorage.removeItem(AUTH_KEY)}

let activeSessionId: string | undefined;
let onUnauthorized: (() => void) | null = null;

async function api<T>(path:string, init?:RequestInit):Promise<T>{
  const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),30000);
  const auth = loadAuth();
  const headers={'Content-Type':'application/json',...(auth?.token?{'Authorization':`Bearer ${auth.token}`}:{}),...(init?.headers||{})};
  let requestInit={...init,signal:controller.signal,headers} as RequestInit;
  if(path==='/assistant/message'&&init?.body){const payload=JSON.parse(String(init.body)) as Record<string,unknown>;if(activeSessionId)payload.session_id=activeSessionId;requestInit.body=JSON.stringify(payload)}
  try{const response=await fetch(`${base}${path}`,requestInit);
    if(response.status===401&&onUnauthorized){onUnauthorized();throw new Error('Your session has expired. Please sign in again.')}
    if(!response.ok){let detail=response.statusText||`Request failed: ${response.status}`;try{const body=await response.json() as {detail?:unknown};if(body.detail)detail=typeof body.detail==='string'?body.detail:JSON.stringify(body.detail)}catch{const body=await response.text();if(body)detail=body}throw new Error(detail)}
    const data=await response.json() as T;if(path==='/assistant/message'&&data&&typeof data==='object'&&'session_id' in data)activeSessionId=String((data as {session_id:string}).session_id);return data
  }finally{clearTimeout(timer)}
}
type Reply={reply:string,intent:string,status:string,sources:{source:string,title:string}[],requires_human:boolean,tool_calls:{name:string,status:string,error_code?:string}[],llm_used:boolean,llm_status:string,llm_error?:string,session_id:string};
type Appointment={id:string,patient_reference:string,specialty:string,starts_at:string,status:string};
type ContentSection={slug:string,title:string,body:string,sort_order:number};
function Mark(){return <span className="brand-mark" aria-hidden="true">+</span>}

// ---------- Login / Signup ----------
function Login({onAuth}:{onAuth:(auth:Auth)=>void}){
  const [mode,setMode]=useState<'login'|'signup'>('login');
  const [email,setEmail]=useState('');const [password,setPassword]=useState('');const [displayName,setDisplayName]=useState('');
  const [error,setError]=useState('');const [loading,setLoading]=useState(false);
  const submit=async()=>{
    setError('');setLoading(true);
    try{
      const path=mode==='login'?'/auth/login':'/auth/signup';
      const body=mode==='login'?{email,password}:{email,password,display_name:displayName||undefined};
      const data=await api<Auth>(path,{method:'POST',body:JSON.stringify(body)});
      saveAuth(data);onAuth(data);
    }catch(err){setError(err instanceof Error?err.message:'Authentication failed')}finally{setLoading(false)}
  };
  return <div className="login-shell"><div className="login-card">
    <Link className="brand" to="/"><Mark/><span>CarePath<small>Patient services</small></span></Link>
    <div className="login-tabs">
      <button className={mode==='login'?'active':''} onClick={()=>{setMode('login');setError('')}}>Sign in</button>
      <button className={mode==='signup'?'active':''} onClick={()=>{setMode('signup');setError('')}}>Create account</button>
    </div>
    <form className="login-form" onSubmit={e=>{e.preventDefault();submit()}}>
      {mode==='signup'&&<label>Full name<input value={displayName} onChange={e=>setDisplayName(e.target.value)} placeholder="Your name" autoComplete="name"/></label>}
      <label>Email<input type="email" required value={email} onChange={e=>setEmail(e.target.value)} placeholder="you@example.com" autoComplete="email"/></label>
      <label>Password<input type="password" required minLength={mode==='signup'?8:1} value={password} onChange={e=>setPassword(e.target.value)} placeholder={mode==='signup'?'At least 8 characters':'Your password'} autoComplete={mode==='signup'?'new-password':'current-password'}/></label>
      {error&&<div className="login-error">{error}</div>}
      <button className="primary-button login-submit" disabled={loading||!email||!password}>{loading?'Please wait…':mode==='login'?'Sign in':'Create account'}</button>
    </form>
    <small className="privacy-note">Your account keeps your appointments private to you. Do not share your password.</small>
  </div></div>;
}

function Layout({children,auth,onSignOut}:{children:React.ReactNode,auth:Auth,onSignOut:()=>void}){
  return <div className="app-shell"><aside className="sidebar"><Link className="brand" to="/"><Mark/><span>CarePath<small>Patient services</small></span></Link><nav className="side-nav"><NavLink to="/" end>⌂ <span>Home</span></NavLink><NavLink to="/assistant">✦ <span>Assistant</span></NavLink><NavLink to="/appointments">▣ <span>My appointments</span></NavLink><NavLink to="/knowledge">▤ <span>Knowledge base</span></NavLink><NavLink to="/evaluation">✓ <span>Evaluation</span></NavLink></nav><div className="sidebar-footer"><span className="status-dot"/> Signed in as <strong>{auth.patient.email}</strong><br/><small>{auth.patient.patient_reference}</small><button className="signout" onClick={onSignOut}>Sign out</button></div></aside><div className="content-shell"><header className="topbar"><span>Patient service workspace</span><span className="topbar-right">Healthcare operations <b>●</b></span></header><main>{children}</main><footer>CarePath · Trusted assistance for everyday care</footer></div></div>
}
function Home(){const [data,setData]=useState<{sections:ContentSection[]}|null>(null);useEffect(()=>{api<typeof data>('/content/overview').then(setData).catch(()=>setData(null))},[]);const hero=data?.sections.find(section=>section.slug==='home_hero');const features=data?.sections.filter(section=>section.slug.startsWith('home_feature_'))||[];return <>{!data?<div className="loading-state">Loading workspace content from Supabase…</div>:<><div className="eyebrow">CAREPATH PATIENT SERVICES</div><section className="hero"><div><h1>{hero?.title||'Patient service operations'}</h1><p>{hero?.body}</p><div className="hero-actions"><Link className="primary" to="/assistant">Start a conversation <span>→</span></Link><Link className="secondary" to="/appointments">My appointments</Link></div></div><div className="hero-card"><div className="pulse-icon">+</div><strong>{hero?.title}</strong><p>{hero?.body}</p><div className="mini-line"><span/> Supabase-backed data</div><div className="mini-line"><span/> Verified workflows</div></div></section><section className="feature-grid">{features.map((feature,index)=><article key={feature.slug}><span className={`feature-icon ${['blue','green','purple'][index%3]}`}>{['✦','▣','◉'][index%3]}</span><h3>{feature.title}</h3><p>{feature.body}</p></article>)}</section></>}</>}
function Badge({children}:{children:React.ReactNode}){return <span className="badge">{children}</span>}
function PageTitle({eyebrow,title,sub}:{eyebrow:string,title:string,sub:string}){return <div className="page-title"><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{sub}</p></div>}type ChatMessage={role:'user'|'assistant',content:string,structured?:Record<string,unknown>};
type StructSlot={slot_id:string,starts_at_local:string,starts_at?:string};
type StructAppt={appointment_id:string,specialty:string|null,starts_at_local:string,status:string};
type Structured={kind?:'slots'|'appointments'|'confirmation'|'error'|'none',specialty?:string|null,date?:string|null,slots?:StructSlot[],appointments?:StructAppt[],outcome?:string|null,appointment_id?:string|null};

function SlotChips({slots,onBook}:{slots:StructSlot[],onBook:(slot:StructSlot)=>void}){
  const [pickedId,setPickedId]=useState<string|null>(null);
  return <div className="slot-grid">
    <div className="slot-grid-label">Available times — click one to book:</div>
    <div className="slot-chips">{slots.map(slot=>
      <button key={slot.slot_id} className={`slot-chip ${pickedId===slot.slot_id?'selected':''} ${pickedId&&pickedId!==slot.slot_id?'disabled':''}`} disabled={!!pickedId&&pickedId!==slot.slot_id} onClick={()=>{if(pickedId)return;setPickedId(slot.slot_id);onBook(slot)}}>{slot.starts_at_local}</button>
    )}</div>
    {pickedId&&<small className="slot-hint">Booking {pickedId}…</small>}
  </div>;
}

function AppointmentChips({items,onAction}:{items:StructAppt[],onAction:(item:StructAppt,action:'cancel'|'reschedule')=>void}){
  return <div className="appt-list">
    <div className="slot-grid-label">Your appointments — use a button to change one:</div>
    <div className="appt-cards">{items.map(item=>{
      const cancelled=item.status==='cancelled';
      const actionable=item.status==='booked'||item.status==='rescheduled'||item.status==='pending_approval';
      return <div key={item.appointment_id} className={`appt-card ${cancelled?'cancelled':''}`}>
        <div className="appt-main"><strong>{item.specialty}</strong><span className="mono appt-ref">{item.appointment_id}</span></div>
        <span className="appt-when">{item.starts_at_local}</span>
        <span className={`appt-status ${cancelled?'struck':''}`}>{cancelled?'Cancelled':item.status==='cancellation_pending_approval'||item.status==='pending_approval'?'Pending approval':item.status==='rescheduled'?'Rescheduled':'Booked'}</span>
        {actionable&&<div className="appt-actions">
          <button onClick={()=>onAction(item,'reschedule')}>Reschedule</button>
          <button className="danger" onClick={()=>onAction(item,'cancel')}>Cancel</button>
        </div>}
      </div>;
    })}</div>
  </div>;
}

// The LLM repeats slot/appointment lists in prose and sometimes leaves bracket
// citations like [sa.doctor/en/insurance] in the text. The UI already renders
// the real cards and a Sources card, so trim the prose to the useful intro.
function tidyProse(raw:string,kind?:string){
  let out=raw.replace(/\*\*/g,'').replace(/\[[^\]\s]*[./][^\]\s]*\]/g,'');
  if(kind==='slots'||kind==='appointments'){
    out=out.split(/(?<=[.!?])\s+/).
      filter(sentence=>!/\bAPT-\d{3,6}\b/.test(sentence)&&!/\b202\d-\d\d-\d\d at \d\d:\d\d\b/.test(sentence)).
      join(' ').replace(/\s*[-–—•]\s*/g,' ').replace(/[ \t]{2,}/g,' ').trim();
  }
  return out;
}

function SourceList({sources}:{sources:{source:string,title:string}[]}){
  if(!sources.length)return null;
  const isUrl=(value:string)=>/^(https?:)?\/\//i.test(value);
  return <div className="source-card">
    <div className="source-label">Sources used for this answer</div>
    <ol className="source-list">{sources.map((source,index)=><li key={index}>{
      isUrl(source.source)?<a href={source.source} target="_blank" rel="noreferrer">{source.title||source.source}</a>:source.title
    }</li>)}</ol>
  </div>;
}

function ConfirmationCard({structured}:{structured:Structured}){
  const booked=structured.outcome==='booked',cancelled=structured.outcome==='cancelled',rescheduled=structured.outcome==='rescheduled';
  return <div className={`confirm-card ${booked?'ok':cancelled?'cancelled':''}`}>
    <span className="confirm-icon">{booked?'✅':cancelled?'🚫':'🔁'}</span>
    <div>
      <strong>{booked?'Appointment booked':cancelled?'Appointment cancelled':'Appointment rescheduled'}</strong>
      {structured.appointment_id&&<div className="mono appt-ref">{structured.appointment_id}</div>}
      <small className="muted">Confirmed by the appointment system.</small>
    </div>
  </div>;
}

function Assistant(){
  const auth=loadAuth();
  const reference=auth?.patient.patient_reference||'';
  const [text,setText]=useState('');
  const [loading,setLoading]=useState(false);
  const [clearing,setClearing]=useState(false);
  const [error,setError]=useState('');
  const [messages,setMessages]=useState<ChatMessage[]>([]);
  const [toolLines,setToolLines]=useState<string[]>([]);
  const [chatSources,setChatSources]=useState<{source:string,title:string}[]>([]);
  const scrollRef=React.useRef<HTMLDivElement>(null);

  React.useEffect(()=>{ // restore persisted chat for this patient
    if(!reference)return;
    api<{messages:ChatMessage[]}>('/chat/history').then(data=>setMessages(data.messages||[])).catch(()=>{})
  },[reference]);
  React.useEffect(()=>{scrollRef.current?.scrollTo({top:scrollRef.current.scrollHeight})},[messages,loading]);

  // Render an assistant bubble ONLY from its structured payload when the
  // backend provided one. Prose fallback for plain-text answers (clinic
  // questions, errors) — no regex guessing, so cancellations, bookings and
  // listings can never be mis-rendered as "pick a time" again.
  function renderAssistant(message:ChatMessage){
    const structured=(message.structured||{}) as Structured;
    const blocks=[];
    if(structured.kind==='slots'&&structured.slots?.length){
      blocks.push(<SlotChips key="slots" slots={structured.slots} onBook={bookSlot}/>);
    }
    if(structured.kind==='appointments'&&structured.appointments?.length){
      blocks.push(<AppointmentChips key="appts" items={structured.appointments} onAction={appointmentAction}/>);
    }
    if(structured.kind==='confirmation'){
      blocks.push(<ConfirmationCard key="confirm" structured={structured}/>);
    }
    const prose=tidyProse(message.content,structured.kind);
    if(blocks.length){
      return <>{blocks}{prose&&<p className="assistant-prose">{prose}</p>}</>;
    }
    return <p className="assistant-prose">{prose||message.content}</p>;
  }

  function appointmentAction(item:StructAppt,action:'cancel'|'reschedule'){
    send(action==='cancel'
      ?`Please cancel appointment ${item.appointment_id}. I confirm this cancellation.`
      :`Please reschedule appointment ${item.appointment_id}`);
  }

  function bookSlot(slot:StructSlot){
    send(`Please book slot ${slot.slot_id} (${slot.starts_at_local})`);
  }

  const send=async(message?:string)=>{
    const payload=(message??text).trim();if(!payload||loading)return;
    setLoading(true);setError('');setText('');
    setMessages(prev=>[...prev,{role:'user',content:payload}]);
    try{
      const data=await api<{reply:string,intent:string,status:string,sources:{source:string,title:string}[],requires_human:boolean,tool_calls:{name:string,status:string,error_code?:string}[],llm_used:boolean,llm_status:string,llm_error?:string,session_id:string,structured?:Record<string,unknown>}>('/assistant/message',{method:'POST',body:JSON.stringify({message:payload})});
      setMessages(prev=>[...prev,{role:'assistant',content:data.reply,structured:data.structured}]);
      setToolLines((data.tool_calls||[]).map(c=>`${c.name} · ${c.status}`));
      setChatSources((data.sources||[]).map(s=>({source:s.source,title:s.title})));
      if(data.status==='failed')setError(data.llm_error||data.reply);
    }catch(err){
      const detail=err instanceof Error?err.message:'Unknown API error';
      setMessages(prev=>[...prev,{role:'assistant',content:`The assistant request failed: ${detail}`}]);
      setError(detail);
    }finally{setLoading(false)}
  };

  const clearChat=async()=>{
    if(clearing)return;
    if(!window.confirm('Clear the entire chat? Your booked appointments and any changes the assistant made stay untouched — only the conversation is deleted.'))return;
    setClearing(true);
    try{await api('/chat/clear',{method:'POST'});setMessages([]);setToolLines([]);setChatSources([])}catch(err){setError(err instanceof Error?err.message:'Could not clear chat')}
    finally{setClearing(false)}
  };

  return <><PageTitle eyebrow="ASSISTANT" title="How can we help today?" sub="Ask about appointments, insurance, clinic policies, or anything you need help navigating. Actions are confirmed by the appointment system before we say they succeeded."/><div className="assistant-layout"><section className="chat-panel">
    <div className="chat-head"><div className="avatar"><Mark/></div><div><strong>CarePath assistant</strong><small>Available now · answers come from tools and cited sources</small></div><span className="online"/></div>
    <div className="messages" ref={scrollRef}>
      <div className="welcome-message"><strong>Good to see you.</strong><p>I can book, reschedule, or cancel appointments, check availability, and answer questions about the clinic and insurance in Saudi Arabia — with sources.</p></div>
      {messages.map((message,index)=>message.role==='user'
        ?<div key={index} className="message user"><p>{message.content}</p></div>
        :<div key={index} className="message assistant-bubble"><div className="assistant-content">{renderAssistant(message)}</div></div>)}
      {loading&&<div className="message assistant-bubble"><div className="assistant-content typing"><span/><span/><span/></div></div>}
    </div>
      {error&&<div className="chat-error">⚠ {error}</div>}
    {(toolLines.length>0||chatSources.length>0)&&<div className="trace-panel">
      {toolLines.map((line,index)=><small key={index} className="tool-line">{line}</small>)}
      <SourceList sources={chatSources}/>
    </div>}
    <div className="suggestions"><button onClick={()=>send('What General Medicine appointments are available this week?')} disabled={loading}>Check availability</button><button onClick={()=>send('I want to book a Dermatology appointment')} disabled={loading}>Book an appointment</button><button onClick={()=>send('Which insurance plans are accepted in Saudi clinics?')} disabled={loading}>Insurance question</button></div>
    <div className="composer">
      <textarea aria-label="Message" value={text} onChange={e=>setText(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}}} placeholder="Type your message…"/>
      <button className="send" onClick={()=>send()} disabled={loading||!text.trim()}>{loading?'…':'↑'}</button>
    </div>
    <div className="chat-footer"><small className="privacy-note">Do not share passwords, payment details, or information about another patient.</small><button className="clear-chat" onClick={clearChat} disabled={clearing}>{clearing?'Clearing…':'🗑 Clear chat'}</button></div>
  </section>
  <aside className="assistant-side"><div className="side-card"><h3>What I can do</h3><p>Book, reschedule, or cancel your appointments</p><p>Check confirmed availability</p><p>Answer clinic and insurance questions with sources</p><p>Show your upcoming appointments</p><p>Connect you with a representative</p></div><div className="side-card soft"><h3>Safety by design</h3><p>I confirm before cancelling or rescheduling, and I only claim success when the appointment system confirms it.</p></div></aside></div></>;
}
function Appointments({auth}:{auth:Auth}){const [items,setItems]=useState<Appointment[]>([]);const [loading,setLoading]=useState(false);const reference=auth.patient.patient_reference;const load=async()=>{setLoading(true);try{const data=await api<{appointments:Appointment[]}>(`/patient/${encodeURIComponent(reference)}/appointments`);setItems(data.appointments)}catch{setItems([])}finally{setLoading(false)}};useEffect(()=>{load()},[]);return <><PageTitle eyebrow="APPOINTMENTS" title="Your appointments" sub={`Live records for ${reference}. Use the assistant to make changes.`}/><div className="toolbar"><Link className="primary" to="/assistant">Manage with assistant →</Link><button className="secondary" onClick={load}>{loading?'Loading…':'Refresh'}</button></div><div className="table-card"><table><thead><tr><th>Reference</th><th>Service</th><th>Date</th><th>Status</th></tr></thead><tbody>{items.length?items.map(item=><tr key={item.id}><td className="mono">{item.id}</td><td>{item.specialty}</td><td>{fmtDateTime(item.starts_at)}</td><td><Badge>{item.status}</Badge></td></tr>):<tr><td colSpan={4} className="empty">{loading?'Loading…':'No appointments found for your account.'}</td></tr>}</tbody></table></div></>}
function Knowledge(){const [data,setData]=useState<{documents:{id:string,title:string,source:string,version:string,requires_validation:boolean,official_url?:string|null}[]}|null>(null);useEffect(()=>{api<typeof data>('/content/knowledge').then(setData).catch(()=>setData(null))},[]);return <><PageTitle eyebrow="KNOWLEDGE BASE" title="Trusted guidance" sub="Documents from the clinic knowledge base, indexed in ChromaDB and used for grounded answers."/>{!data?<div className="loading-state">Loading knowledge documents from Supabase…</div>:<div className="knowledge-grid">{data.documents.map((document,index)=><article className="knowledge-card" key={document.id}><span className={`feature-icon ${['blue','green','purple'][index%3]}`}>▤</span><h3>{document.title}</h3><p>Source: {document.source} · Version {document.version}</p><Badge>{document.requires_validation?'Requires validation':'Approved source'}</Badge>{document.official_url&&<a className="official-link" href={document.official_url} target="_blank" rel="noreferrer">Visit official source ↗</a>}</article>)}</div>}</>}
function Evaluation(){const [data,setData]=useState<{cases:{id:string,category:string}[]}|null>(null);useEffect(()=>{api<typeof data>('/eval/cases').then(setData).catch(()=>setData(null))},[]);return <><PageTitle eyebrow="EVALUATION" title="Quality overview" sub="Cases used to exercise safe assistant behavior and failure handling."/><div className="stat-row"><div><strong>{data?.cases.length||'—'}</strong><span>evaluation cases</span></div><div><strong>6</strong><span>appointment tools</span></div><div><strong>100%</strong><span>cancellations take effect</span></div></div><div className="table-card"><table><thead><tr><th>ID</th><th>Scenario</th><th>Expected behavior</th></tr></thead><tbody>{data?.cases.map(c=><tr key={c.id}><td className="mono">{c.id}</td><td>{c.category}</td><td>Validated and safe response</td></tr>)}</tbody></table></div></>}
function App(){
  const [auth,setAuth]=useState<Auth | null>(loadAuth);
  useEffect(()=>{onUnauthorized=()=>{saveAuth(null);setAuth(null)};return ()=>{onUnauthorized=null}},[]);
  const signOut=()=>{saveAuth(null);activeSessionId=undefined;setAuth(null)};
  if(!auth) return <Login onAuth={setAuth}/>;
  return <Layout auth={auth} onSignOut={signOut}><Routes><Route path="/" element={<Home/>}/><Route path="/assistant" element={<Assistant/>}/><Route path="/appointments" element={<Appointments auth={auth}/>}/><Route path="/knowledge" element={<Knowledge/>}/><Route path="/evaluation" element={<Evaluation/>}/></Routes></Layout>;
}
createRoot(document.getElementById('root')!).render(<BrowserRouter><App/></BrowserRouter>);
