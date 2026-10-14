"""Owned loopback fixture for browser transport tests; never the live server."""
import argparse
import os
from pathlib import Path

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--data',required=True)
    parser.add_argument('--trained',action='store_true')
    args=parser.parse_args()
    os.environ.update(TUPPI_SERVER_DATA_DIR=args.data,TUPPI_SERVER_RULESET='project_target_v3',
        TUPPI_SERVER_REVIEW='0',TUPPI_SERVER_SOOLI_ODDS='0',TUPPI_CONTRACT_ROLLOUT_SAMPLES='0',
        TUPPI_SERVER_AI_ACTION_DELAY_SECONDS='0',TUPPI_SERVER_REVEAL_PAUSE_SECONDS='0',
        TUPPI_BROWSER_ORIGINS=f'http://127.0.0.1:{args.port}',TUPPI_SERVER_AI_PROFILE='tuppi_ai_search_v1' if args.trained else 'first_legal_action_v1')
    if args.trained: os.environ['TUPPI_HOSTED_BOT']='1'
    from tuppi_server import match_runner, rooms
    # Functional transport checks omit presentation delays, retain real search.
    match_runner.REVEAL_PAUSE_SECONDS=match_runner.REVEAL_STEP_SECONDS=0
    rooms.DEFAULT_AI_ACTION_DELAY_MS=0
    if args.trained:
        from tuppi_server.hosted import create_hosted_app
        app=create_hosted_app()
    else:
        from tuppi_rules import RulesetId
        from tuppi_server.app import TuppiASGIApp
        from tuppi_server.hosted import HostedBoundary
        app=HostedBoundary(TuppiASGIApp(rooms.RoomManager(Path(args.data),
            ruleset_id=RulesetId.PROJECT_TARGET_V3,ai_profile_key=match_runner.TEST_AI_PROFILE_KEY)),
            origins={f'http://127.0.0.1:{args.port}'})
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=args.port,lifespan='on' if args.trained else 'off',
        access_log=False,log_level='warning',ws_max_size=32768)

if __name__=='__main__': main()
