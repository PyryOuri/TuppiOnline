from __future__ import annotations
import asyncio
import json
import time

import pytest
from tuppi_rules import RulesetId
from tuppi_server.app import TuppiASGIApp, Connection
from tuppi_server.hosted import HostedBoundary, validate_origins
from tuppi_server.hosted_bot import HostedSearchAgent
from tuppi_server.hosted_site import HostedSite
from tuppi_server.match_runner import LiveMatchRunner, TEST_AI_PROFILE_KEY, TUPPI_AI_PROFILE_KEY
from tuppi_server.rooms import RoomManager, RoomError
from tuppi_engine import action_from_data


async def http(app, path, body=None, origin='https://tuppi.example', method='POST'):
    output=[]
    async def receive():
        return {'type':'http.request','body':json.dumps(body).encode() if body is not None else b'', 'more_body':False}
    async def send(message): output.append(message)
    await app({'type':'http','path':path,'method':method,'headers':[(b'origin',origin.encode())]},receive,send)
    return output[0],json.loads(output[1]['body'])


def test_exact_origin_and_body_and_capacity_guards():
    async def scenario():
        app=HostedBoundary(TuppiASGIApp(RoomManager()),origins={'https://tuppi.example'},max_rooms=1)
        start,_=await http(app,'/healthz',origin='https://evil.example',method='GET')
        assert start['status']==403
        start,body=await http(app,'/v1/compatibility',method='GET')
        assert body['ruleset_id']=='project_target_v3'
        assert (b'access-control-allow-origin',b'https://tuppi.example') in start['headers']
        start,body=await http(app,'/v1/rooms',{'display_name':'x'*17000,'ai_seats':[]})
        assert start['status']==400 and body['error']=='request_too_large'
        start,_=await http(app,'/v1/rooms',{'display_name':'Host','ai_seats':[]})
        assert start['status']==200
        start,body=await http(app,'/v1/rooms',{'display_name':'Host 2','ai_seats':[]})
        assert start['status']==503 and body['error']=='server_busy'
        start,_=await http(app,'/v1/rooms/ABC123/analysis',{})
        assert start['status']==404
        start,_=await http(app,'/v1/rooms/ABC123/join',{'display_name':'Guest'})
        assert start['status']==404 and 'ABC123' not in app.room_locks
    asyncio.run(scenario())
    for value in ('*','http://example.com','https://example.com/path','https://u:p@example.com'):
        with pytest.raises(ValueError): validate_origins(value)
    assert validate_origins('https://tuppi.example,http://127.0.0.1:18740')


def test_room_creation_requires_the_configured_passcode(monkeypatch):
    from tuppi_server.hosted import MAX_PASSCODE_FAILURES_PER_MINUTE, room_passcode_from_environment
    async def scenario():
        app=HostedBoundary(TuppiASGIApp(RoomManager()),origins={'https://tuppi.example'},room_passcode='friends-only-2026')
        _,body=await http(app,'/v1/compatibility',method='GET')
        assert body['create_passcode_required'] is True
        start,body=await http(app,'/v1/rooms',{'display_name':'Host','ai_seats':[]})
        assert start['status']==403 and body['error']=='room_passcode_required'
        start,body=await http(app,'/v1/rooms',{'display_name':'Host','ai_seats':[],'room_passcode':'guess'})
        assert start['status']==403 and body['error']=='invalid_room_passcode' and not app.game.rooms._rooms
        start,body=await http(app,'/v1/rooms',{'display_name':'Host','ai_seats':[],'room_passcode':'friends-only-2026'})
        assert start['status']==200 and body['lobby']['seats'][0]['display_name']=='Host'
        # Invitations need only the room code.
        start,body=await http(app,f"/v1/rooms/{body['room_code']}/join",{'display_name':'Friend'})
        assert start['status']==200 and body['seat']==1
        start,body=await http(app,'/v1/rooms',{'display_name':'x'*17000,'ai_seats':[],'room_passcode':'friends-only-2026'})
        assert start['status']==400 and body['error']=='request_too_large'
        for _ in range(MAX_PASSCODE_FAILURES_PER_MINUTE-1):
            await http(app,'/v1/rooms',{'display_name':'Host','ai_seats':[],'room_passcode':'guess'})
        start,body=await http(app,'/v1/rooms',{'display_name':'Host','ai_seats':[],'room_passcode':'friends-only-2026'})
        assert start['status']==429 and body['error']=='too_many_attempts', 'guessing is throttled'
        assert len(app.game.rooms._rooms)==1
        # Without a configured passcode, creation is open and a stray field is ignored.
        open_app=HostedBoundary(TuppiASGIApp(RoomManager()),origins={'https://tuppi.example'})
        _,body=await http(open_app,'/v1/compatibility',method='GET')
        assert body['create_passcode_required'] is False
        start,_=await http(open_app,'/v1/rooms',{'display_name':'Host','ai_seats':[],'room_passcode':'anything'})
        assert start['status']==200
    asyncio.run(scenario())
    monkeypatch.delenv('TUPPI_ROOM_PASSCODE',raising=False)
    assert room_passcode_from_environment() is None
    for bad in ('short','  padded-passcode  ','x'*129):
        monkeypatch.setenv('TUPPI_ROOM_PASSCODE',bad)
        with pytest.raises(ValueError): room_passcode_from_environment()
    monkeypatch.setenv('TUPPI_ROOM_PASSCODE','friends-only-2026')
    assert room_passcode_from_environment()=='friends-only-2026'


def test_started_room_and_readiness_cannot_be_reconfigured():
    rooms=RoomManager(ruleset_id=RulesetId.PROJECT_TARGET_V3,ai_profile_key=TEST_AI_PROFILE_KEY)
    room,host=rooms.create_room(display_name='Host')
    _,guest=rooms.join_room(code=room.code,display_name='Guest')
    rooms.mark_ready(code=room.code,token=host.token)
    rooms.set_ai_seats(code=room.code,host_token=host.token,ai_seats=frozenset({2,3}))
    assert not host.ready and not guest.ready
    rooms.mark_ready(code=room.code,token=host.token,auto_run_ai=False)
    assert room.runner is None
    rooms.mark_ready(code=room.code,token=guest.token,auto_run_ai=False)
    for call in (lambda:rooms.join_room(code=room.code,display_name='Late'),
                 lambda:rooms.set_ai_seats(code=room.code,host_token=host.token,ai_seats=frozenset({1,2,3}))):
        with pytest.raises(RoomError,match='settings_locked'): call()
    rooms.mark_ready(code=room.code,token=host.token,auto_run_ai=False)
    assert room.lifecycle=='playing'


def test_private_expiry_archives_records_and_preserves_connected_rooms(tmp_path):
    rooms=RoomManager(tmp_path)
    room,host=rooms.create_room(display_name='Host')
    other,_=rooms.create_room(display_name='Other')
    app=HostedBoundary(TuppiASGIApp(rooms),origins={'https://tuppi.example'})
    app.activity[room.code]=app.activity[other.code]=time.time()-2*86400
    app.game._connections[other.code]={host.token:object()}
    app.expire_idle_rooms()
    assert room.code not in rooms._rooms and other.code in rooms._rooms
    assert not (tmp_path/f'room-{room.code}.json').exists()
    assert len(list((tmp_path/'expired').glob(f'room-{room.code}-*.json')))==1
    assert (tmp_path/f'room-{other.code}.json').exists()


def test_controller_cursor_round_trips_private_record(monkeypatch):
    monkeypatch.setenv('TUPPI_HOSTED_BOT','1')
    runner=LiveMatchRunner(match_ref='hosted-cursor',ai_seats=frozenset({1,2,3}),
        ai_profile_key=TUPPI_AI_PROFILE_KEY,ruleset_id=RulesetId.PROJECT_TARGET_V3,auto_run_ai=False)
    for seat,agent in runner._ai_agents.items(): agent.rng_state=123456789+seat
    record=runner.persistence_record()
    assert record['schema_version']=='tuppi.server.match_record.v5'
    restored=LiveMatchRunner.from_persistence_record(record)
    assert {s:a.checkpoint() for s,a in restored._ai_agents.items()} == {s:a.checkpoint() for s,a in runner._ai_agents.items()}
    for seat in range(4):
        assert 'bot_controllers' not in restored.observation(seat)
    record['bot_controllers']['1']['rng']=-1
    with pytest.raises(ValueError,match='controller'): LiveMatchRunner.from_persistence_record(record)


def test_failed_socket_does_not_abort_other_players():
    async def scenario():
        rooms=RoomManager(ai_profile_key=TEST_AI_PROFILE_KEY)
        room,host=rooms.create_room(display_name='Host',ai_seats=frozenset({1,2,3}))
        rooms.mark_ready(code=room.code,token=host.token)
        app=TuppiASGIApp(rooms); received=[]
        async def broken(message): raise OSError('phone asleep')
        async def live(message): received.append(message)
        app._connections[room.code]={'broken':Connection(room.code,'broken',0,broken),
            host.token:Connection(room.code,host.token,0,live)}
        # Lobby broadcasts do not authenticate each connection again.
        await app._broadcast_lobby(room.code)
        assert 'broken' not in app._connections[room.code] and received
    asyncio.run(scenario())


def test_a_stalled_connection_cannot_hold_up_the_room(monkeypatch):
    from tuppi_server import app as app_module
    monkeypatch.setattr(app_module,'SEND_TIMEOUT_SECONDS',0.05)
    async def scenario():
        rooms=RoomManager(ai_profile_key=TEST_AI_PROFILE_KEY)
        room,host=rooms.create_room(display_name='Host',ai_seats=frozenset({1,3}))
        _,guest=rooms.join_room(code=room.code,display_name='Sleeping phone')
        rooms.mark_ready(code=room.code,token=host.token); rooms.mark_ready(code=room.code,token=guest.token)
        app=TuppiASGIApp(rooms); received=[]; closes=[]
        async def stalled(message):
            if message.get('type')=='websocket.close': closes.append(message); return
            await asyncio.Event().wait()  # a phone that stopped reading
        async def live(message): received.append(message)
        app._connections[room.code]={guest.token:Connection(room.code,guest.token,2,stalled),
            host.token:Connection(room.code,host.token,0,live)}
        started=time.perf_counter()
        await app._broadcast_match(room.code)
        await app._broadcast_lobby(room.code)
        assert time.perf_counter()-started<1.0
        assert guest.token not in app._connections[room.code] and len(received)==2
        assert closes==[{'type':'websocket.close','code':1011}]
    asyncio.run(scenario())


def test_restart_at_final_human_card_does_not_invent_a_deal(monkeypatch):
    from tuppi_server import match_runner
    monkeypatch.setattr(match_runner,'REVEAL_PAUSE_SECONDS',0)
    monkeypatch.setattr(match_runner,'REVEAL_STEP_SECONDS',0)
    async def scenario():
        runner=LiveMatchRunner(match_ref='last-card-checkpoint',ruleset_id=RulesetId.PROJECT_TARGET_V3,
            ai_profile_key=TEST_AI_PROFILE_KEY,auto_run_ai=False)
        for seat in range(4):
            action=action_from_data(runner.bidding(seat)['options'][0])
            await runner.submit_async(seat=seat,client_action_id=f'bid-{seat}',match_ref=runner.match_ref,
                expected_event_index=runner.event_cursor,action=action,ai_action_delay_seconds=0)
        record=None
        class CrashAtCommit(Exception): pass
        async def checkpoint():
            nonlocal record
            if runner.state.phase.value=='DEAL_COMPLETE':
                record=runner.persistence_record()
                raise CrashAtCommit()
        try:
            for index in range(52):
                seat=runner.current_actor
                action=action_from_data(runner.observation(seat)['legal_actions'][0])
                await runner.submit_async(seat=seat,client_action_id=f'card-{index}',match_ref=runner.match_ref,
                    expected_event_index=runner.event_cursor,action=action,on_human_action=checkpoint,ai_action_delay_seconds=0)
        except CrashAtCommit: pass
        assert record is not None
        restored=LiveMatchRunner.from_persistence_record(record)
        assert restored.event_cursor==runner.event_cursor
        assert restored.state.phase.value=='DEAL_COMPLETE'
        assert len(restored._deals)==1
        assert restored.observation(0)==runner.observation(0)
    asyncio.run(scenario())


def test_only_one_bot_room_is_admitted_until_capacity_is_qualified():
    rooms=RoomManager(ruleset_id=RulesetId.PROJECT_TARGET_V3,ai_profile_key=TEST_AI_PROFILE_KEY)
    game=HostedBoundary(TuppiASGIApp(rooms),origins={'https://tuppi.example'})
    first,host=rooms.create_room(display_name='First',ai_seats=frozenset({1,2,3}))
    rooms.mark_ready(code=first.code,token=host.token,auto_run_ai=False)
    second,guest=rooms.create_room(display_name='Second',ai_seats=frozenset({1,2,3}))
    with pytest.raises(RoomError,match='server_busy'):
        rooms.mark_ready(code=second.code,token=guest.token,auto_run_ai=False)
    assert second.runner is None and not guest.ready


def test_completed_rooms_do_not_consume_active_room_capacity():
    from types import SimpleNamespace
    async def scenario():
        rooms=RoomManager()
        old,_=rooms.create_room(display_name='Finished')
        old.runner=SimpleNamespace(terminal=True)
        app=HostedBoundary(TuppiASGIApp(rooms),origins={'https://tuppi.example'},max_rooms=1)
        status,_=await http(app,'/v1/rooms',{'display_name':'New game','ai_seats':[]})
        assert status['status']==200 and len(rooms._rooms)==2
        assert old.code in rooms._rooms
    asyncio.run(scenario())


def test_static_delivery_has_correct_wasm_and_script_mime_and_private_paths_are_denied(tmp_path):
    async def scenario():
        (tmp_path/'offline-manifest.json').write_text(json.dumps({'files':[{'path':'index.html'},{'path':'tuppi.wasm'},{'path':'client.1234567890abcdef.mjs'}]}))
        for path,body in [('index.html',b'<title>Tuppi</title>'),('tuppi.wasm',b'\x00asm'),('client.1234567890abcdef.mjs',b'export{}')]:
            (tmp_path/path).write_bytes(body)
        (tmp_path/'secret.json').write_text('private')
        app=HostedSite(HostedBoundary(TuppiASGIApp(RoomManager()),origins={'https://tuppi.example'}),tmp_path,'https://tuppi.example')
        async def get(path):
            output=[]
            async def send(message):output.append(message)
            async def receive():return {'type':'http.request','body':b''}
            await app({'type':'http','path':path,'method':'GET','headers':[]},receive,send)
            return output
        wasm=await get('/tuppi.wasm');assert dict(wasm[0]['headers'])[b'content-type']==b'application/wasm'
        script=await get('/client.1234567890abcdef.mjs');assert b'immutable' in dict(script[0]['headers'])[b'cache-control']
        assert b'javascript' in dict(script[0]['headers'])[b'content-type']
        for path in ('/secret.json','/../secret.json','/data/rooms','/.git/config'):
            assert (await get(path))[0]['status']==404
        config=await get('/deployment.json')
        assert json.loads(config[1]['body'])['backend']=='https://tuppi.example'
    asyncio.run(scenario())


def test_lite_level_cursor_round_trips_and_rejects_other_checkpoints(monkeypatch):
    monkeypatch.setenv('TUPPI_HOSTED_BOT','1'); monkeypatch.setenv('TUPPI_HOSTED_BOT_LEVEL','lite')
    from tuppi_server.hosted_bot import HostedLiteAgent
    runner=LiveMatchRunner(match_ref='hosted-lite-cursor',ai_seats=frozenset({1,2,3}),
        ai_profile_key=TUPPI_AI_PROFILE_KEY,ruleset_id=RulesetId.PROJECT_TARGET_V3,auto_run_ai=False)
    assert all(type(a) is HostedLiteAgent for a in runner._ai_agents.values())
    for seat,agent in runner._ai_agents.items(): agent.rng_state=987654321+seat
    record=runner.persistence_record()
    restored=LiveMatchRunner.from_persistence_record(record)
    assert {s:a.checkpoint() for s,a in restored._ai_agents.items()} == {s:a.checkpoint() for s,a in runner._ai_agents.items()}
    full=dict(record,bot_controllers={k:{'schema':'tuppi.hosted.controller.v1','worlds':1024,'rng':1} for k in record['bot_controllers']})
    with pytest.raises(ValueError,match='controller'): LiveMatchRunner.from_persistence_record(full)


def test_lite_bot_plays_a_complete_deal_through_the_runner(monkeypatch):
    monkeypatch.setenv('TUPPI_HOSTED_BOT','1'); monkeypatch.setenv('TUPPI_HOSTED_BOT_LEVEL','lite')
    from tuppi_server.hosted_bot import hosted_agents
    from tuppi_engine import ExplicitDeal, apply_match_action, begin_explicit_deal, create_match, match_observation_for
    from tuppi_engine.state import ACTIVE_PHASES
    from tuppi_rules import MatchScore
    from tuppi_rules.cards import FULL_DECK
    agents=hosted_agents(range(4)); cards=list(FULL_DECK)
    state=begin_explicit_deal(create_match(initial_score=MatchScore(0,0),initial_dealer=0,match_ref='lite-deal',
        ruleset_id=RulesetId.PROJECT_TARGET_V3),ExplicitDeal(dealer=0,hands=tuple(tuple(cards[s::4]) for s in range(4))))
    while state.phase in ACTIVE_PHASES:
        seat=state.current_actor; state=apply_match_action(state,agents[seat].choose_action(match_observation_for(state,seat)))
    assert state.completed_deals and agents[0].last_stats['decision_seconds']<1


def test_bot_level_is_validated_and_lite_admits_bots_in_every_room(monkeypatch):
    from tuppi_server.hosted import bot_room_limit, verify_bot_identity
    from tuppi_server.hosted_bot import level
    monkeypatch.setenv('TUPPI_HOSTED_BOT_LEVEL','fast')
    with pytest.raises(ValueError,match='lite or full'): level()
    assert bot_room_limit('full',8)==1 and bot_room_limit('lite',8)==8
    rooms=RoomManager(ruleset_id=RulesetId.PROJECT_TARGET_V3,ai_profile_key=TEST_AI_PROFILE_KEY)
    HostedBoundary(TuppiASGIApp(rooms),origins={'https://tuppi.example'},max_bot_rooms=bot_room_limit('lite',8))
    for index in range(3):
        room,host=rooms.create_room(display_name=f'Room {index}',ai_seats=frozenset({1,2,3}))
        rooms.mark_ready(code=room.code,token=host.token,auto_run_ai=False)
        assert room.runner is not None
    identity=verify_bot_identity('lite')
    assert identity['profile']=='tuppi_ai_lite_v1' and identity['search'] is None
