from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.agent import DisputeAgent
from app.ai_clients import AIClients
from app.config import get_settings
from app.data import DataStore
from app.payouts.payswift import PaySwiftClient
from app import storage


class Message(BaseModel):
    message_id: str
    rider_id: str
    text: str
    received_at: str


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    storage.init_db()
    app.state.agent = DisputeAgent(DataStore(settings.data_dir), AIClients(settings), PaySwiftClient(settings.payswift_base_url))
    yield


app = FastAPI(title="QuickDrop Rider Payout Dispute Desk", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/messages")
def messages(message: Message) -> dict[str, str]:
    try:
        return {"reply": app.state.agent.handle(**message.model_dump())}
    except Exception as error:
        storage.trace(message.rider_id, "error", "message_processing", message.model_dump(), {"error": str(error)})
        raise HTTPException(status_code=503, detail="Message could not be processed") from error


@app.get("/trace/{rider_id}")
def get_trace(rider_id: str):
    return storage.get_trace(rider_id)

@app.get("/ops/riders")
def get_active_riders():
    return storage.get_riders_with_activity()


@app.get("/ops/pending")
def get_pending():
    return storage.pending_ops()


@app.post("/ops/{item_id}/{decision}")
def decide(item_id: str, decision: str):
    if decision not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="decision must be approved or rejected")
    item = storage.get_ops_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="pending item not found")
    if decision == "approved" and item["type"] == "approval" and item["amount"]:
        try:
            app.state.agent.payswift.create_payout(item["rider_id"], item["amount"], f"Ops approval {item_id}", f"approval:{item_id}")
        except Exception as error:
            storage.trace(item["rider_id"], "error", "approved_payout", item, {"error": str(error)})
            raise HTTPException(status_code=503, detail="PaySwift payout failed; approval remains pending") from error
    if not storage.decide_ops_item(item_id, decision):
        raise HTTPException(status_code=409, detail="pending item was already decided")
    return {"status": decision}


@app.get("/ops", response_class=HTMLResponse)
def ops_dashboard() -> str:
    return """<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>QuickDrop Ops</title><style>body{font:16px system-ui;max-width:1100px;margin:32px auto;padding:0 16px;background:#f4f1e9;color:#17221d}.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.panel{background:#fff;border:1px solid #d5ddd5;border-radius:10px;padding:16px}h1{margin-top:0}li{margin:10px 0}.trace{width:100%;height:520px;box-sizing:border-box;font:12px ui-monospace,monospace}@media(max-width:700px){.grid{grid-template-columns:1fr}}</style></head><body><h1>QuickDrop Operations</h1><div class="grid"><section class="panel"><h2>Pending work</h2><ul id="items"><li>Loading...</li></ul></section><section class="panel"><h2>Conversation trace</h2><select id="riders" onchange="showTrace()"><option>Select a rider</option></select><textarea id="trace" class="trace" readonly>Select a rider to inspect messages, AI calls, reconciliation, decisions and replies.</textarea></section></div><script>async function decide(id,action){await fetch('/ops/'+id+'/'+action,{method:'POST'});load()}async function load(){const items=await (await fetch('/ops/pending')).json();document.querySelector('#items').innerHTML=items.map(x=>'<li><b>'+x.type+'</b> '+x.rider_id+' '+(x.amount?'₹'+x.amount:'')+'<br>'+x.reason+(x.type==='approval'?' <button onclick="decide(\\''+x.id+'\\',\\'approved\\')">Approve</button><button onclick="decide(\\''+x.id+'\\',\\'rejected\\')">Reject</button>':'</li>')).join('')||'<li>Nothing pending</li>';const riders=await (await fetch('/ops/riders')).json();document.querySelector('#riders').innerHTML='<option>Select a rider</option>'+riders.map(x=>'<option>'+x+'</option>').join('')}async function showTrace(){const rider=document.querySelector('#riders').value;if(rider&&rider!=='Select a rider')document.querySelector('#trace').value=JSON.stringify(await (await fetch('/trace/'+rider)).json(),null,2)}load();setInterval(load,5000)</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return """<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>QuickDrop Chat</title><style>body{font:16px system-ui;max-width:760px;margin:32px auto;padding:0 16px;background:#f4f1e9;color:#17221d}.chat{background:white;border:1px solid #d5ddd5;border-radius:12px;overflow:hidden}.head{padding:18px;border-bottom:1px solid #e5e9e5;font-weight:700}.head small{display:block;color:#69756c;font-weight:400;margin-top:4px}.messages{height:440px;overflow:auto;padding:18px;background:#fbfcfa}.bubble{max-width:78%;padding:11px 14px;border-radius:14px;margin:9px 0;white-space:pre-wrap}.rider{margin-left:auto;background:#d8eadc}.agent{background:white;border:1px solid #e1e6df}.empty{text-align:center;color:#8a938c;padding-top:180px}.composer{display:flex;gap:8px;padding:12px;border-top:1px solid #e5e9e5}.composer input{padding:11px;border:1px solid #cbd4cb;border-radius:7px;font:inherit}.id{width:85px}.text{flex:1}.composer button,button{background:#1f6b4d;color:white;border:0;border-radius:7px;padding:0 16px;font-weight:700}.ops{margin-top:16px;background:white;padding:16px;border:1px solid #d5ddd5;border-radius:10px}.ops h2{font-size:16px;margin:0 0 8px}li{margin:8px 0}li button{padding:6px;margin-left:4px}@media(max-width:600px){.composer{flex-wrap:wrap}.id{width:100%}.text{width:calc(100% - 80px)}} </style></head><body><h1>QuickDrop Support</h1><p>Chat about a rider payout or order.</p><section class="chat"><div class="head">Payout assistant<small>Replies use verified trip and PaySwift records.</small></div><div class="messages" id="messages"><div class="empty">Describe the payout problem to start.</div></div><form class="composer" id="form"><input class="id" id="rider" value="R003" aria-label="Rider ID"><input class="text" id="text" required placeholder="Type a message..." aria-label="Message"><button id="send">Send</button></form></section><section class="ops"><h2>Pending ops work</h2><ul id="items"><li>Loading...</li></ul></section><script>const box=document.querySelector('#messages'),form=document.querySelector('#form'),send=document.querySelector('#send');function bubble(text,kind){const empty=box.querySelector('.empty');if(empty)empty.remove();const node=document.createElement('div');node.className='bubble '+kind;node.textContent=text;box.appendChild(node);box.scrollTop=box.scrollHeight}form.addEventListener('submit',async event=>{event.preventDefault();const rider=document.querySelector('#rider').value.trim(),text=document.querySelector('#text').value.trim();if(!rider||!text)return;bubble(text,'rider');document.querySelector('#text').value='';send.disabled=true;try{const response=await fetch('/messages',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message_id:'web-'+crypto.randomUUID(),rider_id:rider,text,received_at:new Date().toISOString()})});const data=await response.json();bubble(response.ok?data.reply:'The agent could not process that message.','agent');load()}catch(error){bubble('Connection error. Check that the API is running.','agent')}finally{send.disabled=false;document.querySelector('#text').focus()}});async function decide(id,action){await fetch('/ops/'+id+'/'+action,{method:'POST'});load()}async function load(){const items=await (await fetch('/ops/pending')).json();document.querySelector('#items').innerHTML=items.map(x=>'<li><b>'+x.type+'</b> '+x.rider_id+' '+(x.amount?'₹'+x.amount:'')+'<br>'+x.reason+' <button onclick="decide(\\''+x.id+'\\',\\'approved\\')">Approve</button><button onclick="decide(\\''+x.id+'\\',\\'rejected\\')">Reject</button></li>').join('')||'<li>Nothing pending</li>'}load();setInterval(load,5000)</script></body></html>"""