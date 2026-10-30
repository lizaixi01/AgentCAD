"""Process completion must not discard the runner's final buffered events."""
import json
import subprocess
import time

import pytest

from agentcad.backends.freecad import _wait_reporting


@pytest.mark.parametrize('already_finished',[True,False])
def test_progress_drains_complete_lines_after_process_exit(tmp_path,already_finished):
    log=tmp_path/'progress.jsonl';received=[]
    log.write_text(json.dumps({'step':0})+'\n',encoding='utf-8')
    class Process:
        calls=0
        def wait(self,timeout):
            self.calls+=1
            if not already_finished and self.calls==1:
                raise subprocess.TimeoutExpired('test-process',timeout)
            with log.open('a',encoding='utf-8') as stream:
                stream.write(json.dumps({'phase':'checking'})+'\n')
            return 0
    _wait_reporting(Process(),log,time.perf_counter()+10,received.append)
    assert received==[{'step':0},{'phase':'checking'}]
