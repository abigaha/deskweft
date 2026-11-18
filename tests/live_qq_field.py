"""Opt-in, read-only QQ field check. Use --live for one authorized normal auto-login."""

import argparse
import asyncio
from contextlib import closing
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

import psutil
import win32api
import win32con
import win32gui
import win32job
import win32process

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'skills/windows-app-automation/scripts'))
import private_desktop as desktop
from qq_private_probe import load_runtime, response_data

EXE = Path(os.environ['ProgramFiles']) / 'Tencent/QQ.exe'
LABELS = ('联系人', '登录')
FLAGS = ('--force-renderer-accessibility', '--disable-backgrounding-occluded-windows',
         '--disable-features=CalculateNativeWinOcclusion')
ROLES = {50000: 'ButtonControl', 50002: 'CheckBoxControl', 50005: 'HyperlinkControl',
         50007: 'ListItemControl', 50011: 'MenuItemControl', 50013: 'RadioButtonControl',
         50019: 'TabItemControl'}
WIDGET = 'Chrome_WidgetWin_1'
RENDERER = 'Chrome_RenderWidgetHostHWND'


class StopProbe(Exception):
    pass


def require(test, reason):
    if not test:
        raise StopProbe(reason)


def qq_pids():
    return {p.pid for p in psutil.process_iter(['name']) if (p.info['name'] or '').lower() == 'qq.exe'}


def self_check():
    assert allowed_value('联系人') == '联系人' and allowed_value('登录') == '登录'
    assert allowed_value('unlisted') is None and allowed_value({'name': '联系人'}) is None
    assert not agrees({'target': '联系人', 'result': None}, '联系人', '联系人')
    assert not agrees({'result': '联系人', 'ok': True}, '联系人', '联系人')
    assert agrees({'result': '联系人', 'ok': True, 'execution_state': 'completed',
                   'call_completed': True, 'result_truncated': False}, '联系人', '联系人')


def allowed_value(value):
    return value if isinstance(value, str) and value in LABELS else None


def agrees(reply, direct, expected):
    return (reply.get('ok') is True and reply.get('execution_state') == 'completed'
            and reply.get('call_completed') is True and reply.get('result_truncated') is False
            and allowed_value(reply.get('result')) == direct == expected and expected in LABELS)


def job_members(job):
    return set(win32job.QueryInformationJobObject(job, win32job.JobObjectBasicProcessIdList))


def window_handles(hwnd, owned, expected):
    handles = []
    win32gui.EnumChildWindows(hwnd, lambda h, _: handles.append(h) or True, None)
    for h in (hwnd, *handles):
        tid, pid = win32process.GetWindowThreadProcessId(h)
        require(pid in owned and desktop.object_name(desktop.U.GetThreadDesktop(tid)) == expected,
                'window ownership or desktop changed')
    return sorted(handles)


def worker_setup():
    """Keep raw native captions, tree diagnostics and unexpected provider values inside the worker."""
    runtime = load_runtime(REPO)
    from deskweft import tree
    production_dispatch = runtime.uia_worker._make_dispatch
    read = tree.read_detailed
    stats = {}

    def counted(*args, **kwargs):
        result = read(*args, **kwargs)
        stats.update({k: result[k] for k in ('timed_out', 'limit_reached', 'identity_complete')})
        stats['elements'] = len(result['elements'])
        return result

    def make_dispatch():
        routes = production_dispatch()

        def safe(action, **params):
            hwnd = params['hwnd']
            with closing(win32job.OpenJobObject(win32job.JOB_OBJECT_QUERY, False, os.environ['QQ_FIELD_JOB'])) as job:
                owned = job_members(job)
                require(os.getpid() in owned and win32gui.GetClassName(hwnd) in (WIDGET, RENDERER)
                        and Path(psutil.Process(win32process.GetWindowThreadProcessId(hwnd)[1]).exe()) == EXE,
                        'dispatch target changed')
                window_handles(hwnd, owned, os.environ['DESKWEFT_PRIVATE_EXPECTED'])
            if action == 'see':
                require(params.get('native_only') and not params.get('with_tree'), 'native-only required')
            else:
                require(params['pattern'] == 'LegacyIAccessiblePattern' and params['method'] == 'Name'
                        and not params.get('allow_foreground') and not params.get('args'), 'read-only call required')
            stats.clear()
            raw = routes[action](**params)
            meta = raw.get('meta', raw)
            evidence = meta.get('_probe_worker', {})
            proof = {k: evidence[k] for k in ('pid', 'tid', 'before', 'after') if k in evidence}
            proof['guard_ok'] = all(k not in evidence for k in ('before_error', 'after_error', 'function_error'))
            safe_meta = {k: meta[k] for k in ('ok', 'execution_state', 'call_completed', 'result_truncated') if k in meta}
            safe_meta['_probe_worker'] = proof
            if meta.get('ok') is not True:
                safe_meta['reason'] = next((r for r in ('tree incomplete', 'no such control', 'ambiguous control',
                    'pattern unavailable', 'provider error', 'private guard failed') if r == meta.get('reason')), 'other')
            if action == 'see' and 'meta' in raw:
                require(raw.get('png') is None and 'elements' not in meta, 'unexpected native payload')
                safe_meta.update(handles=sorted(r['hwnd'] for r in meta['native_children']),
                                 truncated=meta['native_children_truncated'])
                return {'meta': safe_meta, 'png': None}
            safe_meta.update(result=allowed_value(meta.get('result')), tree=dict(stats))
            return safe_meta

        return {action: partial(safe, action)
                for action in ('see', 'invoke_pattern')}

    tree.read_detailed = counted
    runtime.uia_worker._make_dispatch = make_dispatch


def public_hits(uia, hwnd, label, owned):
    from comtypes.gen import UIAutomationClient as U
    root = uia.ElementFromHandle(hwnd)
    rows = root.FindAll(U.TreeScope_Descendants, uia.CreatePropertyCondition(U.UIA_NamePropertyId, label))
    hits = []
    for i in range(rows.Length):
        el = rows.GetElement(i)
        role = el.CurrentControlType
        if role not in ROLES or (label == '登录' and role != U.UIA_ButtonControlTypeId) or el.CurrentIsOffscreen:
            continue
        require(el.CurrentProcessId in owned, 'UIA provider element outside job')
        actual = allowed_value(el.CurrentName)
        if actual != label:
            continue
        box = el.CurrentBoundingRectangle
        selector = {'control_type': ROLES[role], 'rect': [box.left, box.top, box.right-box.left, box.bottom-box.top]}
        walker = uia.ControlViewWalker
        adjacent = [walker.GetPreviousSiblingElement(el), walker.GetNextSiblingElement(el)]
        parent = walker.GetParentElement(el)
        hits.append((selector, {'actual': actual, 'role': ROLES[role], 'sibling_role_ids':
                    [s.CurrentControlType for s in adjacent if s], 'parent_role_id': parent.CurrentControlType if parent else None}))
    return rows.Length, hits


def child_env(identity, job_name):
    os.environ.update(DESKWEFT_PRIVATE_EXPECTED=identity['current_desktop'], DESKWEFT_PRIVATE_INPUT=identity['input_desktop'],
                      DESKWEFT_PRIVATE_STATION=identity['window_station'], DESKWEFT_PRIVATE_SESSION=str(identity['session']),
                      QQ_FIELD_JOB=job_name)


def launch_qq(job, identity):
    require(not qq_pids(), 'existing QQ preserved')
    startup = win32process.STARTUPINFO()
    startup.lpDesktop = identity['window_station'] + '\\' + identity['current_desktop']
    hp, ht, pid, _ = win32process.CreateProcess(str(EXE), subprocess.list2cmdline([str(EXE), *FLAGS]), None, None,
        False, win32con.CREATE_SUSPENDED | win32con.CREATE_NO_WINDOW, None, str(EXE.parent), startup)
    with closing(hp), closing(ht):
        root = psutil.Process(pid)
        require(win32job.IsProcessInJob(hp, job) and Path(root.exe()) == EXE and qq_pids() == {pid},
                'exclusive suspended QQ ownership failed')
        require(win32process.ResumeThread(ht) == 1, 'QQ resume failed')
    return root


async def observe(runtime, client, uia, job, identity, report, save):
    from comtypes import COMError
    name = identity['current_desktop']
    root = launch_qq(job, identity)
    report.update(launch_count=1, root_pid=root.pid, suspended_image_and_job_verified=True)
    start = time.monotonic()
    samples, attempts = report['pages'], report['calls']
    verified = {}
    known_pids = {root.pid}
    save()

    async def call(action, hwnd, **params):
        before = window_handles(hwnd, job_members(job), name)
        reply = await client.call_tool(action, dict(hwnd=hwnd, timeout_ms=16000, **params))
        require([b.type for b in reply.content] == ['text'], 'unexpected MCP payload')
        data = response_data(reply)
        p = data.get('_probe_worker', {})
        w = runtime.uia_worker._worker
        require(w and p.get('guard_ok') and p.get('pid') == w['process'].pid and p['pid'] in job_members(job)
                and all(p.get(side) and p[side]['current_full'] == identity['current_full']
                        and p[side]['input_full'] == identity['input_full'] and p[side]['isolated']
                        and p[side]['pid'] == p['pid'] and p[side]['native_tid'] == p['tid'] for side in ('before','after'))
                and desktop.object_name(desktop.U.GetThreadDesktop(p['tid'])) == name, 'real worker dispatch unverified')
        after = window_handles(hwnd, job_members(job), name)
        report['worker'] = {'pid': p['pid'], 'tid': p['tid'], 'private_before_after': True, 'in_job': True}
        known_pids.add(p['pid'])
        if action == 'see':
            report['native'] = {'count': len(data.get('handles', ())), 'win32_before': len(before), 'win32_after': len(after),
                                'set_equal': data.get('ok') is True and data.get('truncated') is False
                                             and before == data.get('handles') == after}
        return data

    async def field(hwnd, label, selector, direct, owned):
        options = [(hwnd, selector)]
        for h in window_handles(hwnd, owned, name):
            if win32gui.GetClassName(h) == RENDERER and win32process.GetWindowThreadProcessId(h)[1] in owned:
                options.append((h, selector))
        options.append((hwnd, {'name': label, 'control_type': selector['control_type']}))
        for h, target in options:
            data = await call('invoke_pattern', h, pattern='LegacyIAccessiblePattern', method='Name', target=target,
                              args=[], allow_foreground=False)
            entry = {'expected': label, 'window_class': win32gui.GetClassName(h), 'selector_fields': list(target),
                     **{k: data[k] for k in ('ok', 'execution_state', 'call_completed', 'result_truncated', 'result', 'reason', 'tree') if k in data}}
            attempts.append(entry)
            save()
            require(data.get('execution_state') != 'unknown', 'provider outcome unknown')
            if agrees(data, direct['actual'], label):
                _, fresh = public_hits(uia, hwnd, label, job_members(job))
                if len(fresh) == 1 and fresh[0][1]['actual'] == label and fresh[0][1]['role'] == direct['role']:
                    report['fields'][label] = {'expected': label, 'legacy_name': data['result'], 'direct_uia': fresh[0][1],
                        'direct_find_before_and_after': True, 'unique_visible_role_match': True}
                    return True
        return False

    tried = {}
    while True:
        owned = job_members(job)
        qq = qq_pids()
        require(qq and qq <= owned,
                'QQ exited or unowned QQ appeared')
        known_pids |= owned
        report['_observed_pids'] = sorted(known_pids)
        stamps = report.setdefault('observed_qq_pid_create_times', {})
        for pid in qq:
            try:
                stamps[str(pid)] = psutil.Process(pid).create_time()
            except psutil.NoSuchProcess:
                continue
        tops = [h for h in runtime.launch._all_top_level_windows() if runtime.launch._window_pid(h) in qq
                and runtime.win32.class_name(h) == WIDGET]
        hits = {s: [] for s in LABELS}
        raw_counts = dict.fromkeys(LABELS, 0)
        com_errors = 0
        visible = [h for h in tops if win32gui.IsWindowVisible(h)]
        def scan(h):
            nonlocal com_errors
            try:
                for label in LABELS:
                    count, found = public_hits(uia, h, label, owned)
                    raw_counts[label] += count
                    hits[label].extend((h, *f) for f in found)
            except COMError:
                com_errors += 1
        renderers = []
        for h in visible:
            renderers.extend(c for c in window_handles(h, owned, name) if runtime.win32.class_name(c) == RENDERER)
            scan(h)
        if not any(hits.values()):
            for h in renderers:
                scan(h)
        if visible and (not report.get('role_counts') or not any(hits.values())):
            try:
                element = uia.ElementFromHandle(visible[0])
                report['role_counts'] = {role: element.FindAll(4, uia.CreatePropertyCondition(30003, code)).Length
                                         for role, code in [('Button', 50000), ('CheckBox', 50002), ('Document', 50030)]}
            except COMError:
                com_errors += 1
        state = {'widgets': len(tops), 'visible': len(visible), 'renderers': len(renderers),
                 'name_hits': raw_counts, 'visible_role_hits': {s: len(v) for s,v in hits.items()}, 'uia_errors': com_errors}
        elapsed = round(time.monotonic()-start, 1)
        if samples and state == samples[-1]['state']:
            samples[-1].update(last_s=elapsed, n=samples[-1]['n']+1)
        else:
            samples.append({'first_s': elapsed, 'last_s': elapsed, 'n': 1, 'state': state})
        save()
        for label in LABELS:
            if len(hits[label]) != 1:
                continue
            h, selector, direct = hits[label][0]
            if 'version' not in report:
                info = response_data(await client.call_tool('app_info', {'hwnd': h}))
                require(info.get('ok') and info['pid'] == runtime.launch._window_pid(h) and info['pid'] in owned and Path(info['exe']) == EXE, 'app identity mismatch')
                report['version'] = {k: info[k] for k in ('version', 'source', 'file_version')}
            if not report.get('native', {}).get('set_equal'):
                await call('see', h, native_only=True, max_elements=160)
            key = (label, h)
            if key not in verified and tried.get(key, 0) < 2:
                tried[key] = tried.get(key, 0) + 1
                if await field(h, label, selector, direct, owned):
                    verified[key] = True
            if key in verified and label == LABELS[0]:
                return 'main_navigation'
        if time.monotonic()-start >= 70:
            if len(hits['登录']) == 1 and ('登录', hits['登录'][0][0]) in verified and not hits['联系人'] and samples[-1]['n'] >= 2:
                return 'login_page'
            raise StopProbe('no stable two-source page field within observation interval')
        await asyncio.sleep(1.5)

def child(name, job_name, out):
    try:
        stream = out.open('x', encoding='utf-8')
    except OSError:
        return 1
    with stream:
        return run_child(name, job_name, stream)


def run_child(name, job_name, stream):
    import comtypes.client
    from comtypes.gen import UIAutomationClient as U
    report = {'completed': False, 'launch_count': 0, 'pages': [], 'fields': {}, 'calls': []}

    def save():
        stream.seek(0)
        json.dump(report, stream, ensure_ascii=False)
        stream.truncate()
        stream.flush()

    runtime = None
    try:
        identity = desktop.verify_dispatch_thread(name)
        child_env(identity, job_name)
        runtime = load_runtime(REPO)
        require(Path(runtime.server.__file__).resolve().parent == REPO / 'deskweft' and
                Path(runtime.uia_worker.__file__).resolve().parent == REPO / 'deskweft', 'workspace source required')
        uia = comtypes.client.CreateObject(U.CUIAutomation, interface=U.IUIAutomation)
        with closing(win32job.OpenJobObject(win32job.JOB_OBJECT_QUERY, False, job_name)) as job:
            require(os.getpid() in job_members(job), 'runner outside launcher job')
            report.update(input_desktop=identity['input_desktop'], private_desktop=name, runner_pid=os.getpid())

            async def run():
                async with runtime.Client(runtime.server.mcp) as client:
                    return await observe(runtime, client, uia, job, identity, report, save)

            report['page'] = asyncio.run(run())
            report['completed'] = True
    except Exception as error:
        report['error'] = str(error) if isinstance(error, StopProbe) else type(error).__name__
        import traceback
        report['error_frames'] = [f'{f.name}:{f.lineno}' for f in traceback.extract_tb(error.__traceback__)
                                  if Path(f.filename).name == Path(__file__).name]
    finally:
        if runtime:
            runtime.uia_worker.close()
            report['worker_closed'] = runtime.uia_worker._worker is None
        save()
    return 0 if report['completed'] else 1


def read_child(path):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        return {'completed': False, 'child_report_error': type(error).__name__}
    if not isinstance(data, dict) or type(data.get('completed')) is not bool:
        return {'completed': False, 'child_report_error': 'expected object with boolean completed'}
    return data


def live():
    job_name = 'DeskWeft_QQ_Field_' + uuid.uuid4().hex

    class NamedJob(desktop._Native):
        def create_job(self):
            handle = win32job.CreateJobObject(None, job_name)
            require(win32api.GetLastError() != 183, 'job name collision')
            return handle.Detach()

    report = {'kind': 'live installed QQ', 'date_local': time.strftime('%Y-%m-%d'), 'expected_main': LABELS[0],
              'fallback': LABELS[1], 'field_source': 'workspace FastMCP in-memory Client -> spawned DeskWeft worker -> LegacyIAccessiblePattern.Name',
              'comparison_source': 'separate runner process -> Windows IUIAutomation.FindAll(exact Name) -> CurrentName and control roles',
              'account_policy': 'normal retained-account auto-login allowed; no explicit login or logout', 'flags': list(FLAGS),
              'initial_qq_process_count': len(qq_pids()), 'exe': str(EXE),
              'exe_sha256': hashlib.sha256(EXE.read_bytes()).hexdigest()}
    builds = list((EXE.parent/'versions').glob('*/resources/app/package.json'))
    if len(builds) == 1:
        package = json.loads(builds[0].read_text(encoding='utf-8'))
        report['installed_build'] = package.get('version') if package.get('productName') == 'QQ' else None
    if report['initial_qq_process_count']:
        print(json.dumps(dict(report, passed=False, stage='existing QQ preserved', launch_count=0), ensure_ascii=False))
        return 1
    with tempfile.TemporaryDirectory(prefix='deskweft-qq-field-') as folder:
        temp = Path(folder).resolve(strict=True)
        require(temp.parent == Path(tempfile.gettempdir()).resolve(strict=True), 'unexpected temporary root')
        stat = temp.stat()
        result = desktop.launch([__file__, '--live', '--job', job_name], temp/'parent.json', timeout=145, api=NamedJob())
        path = Path(result['child_out'])
        report.update(read_child(path))
        pids = set(report.pop('_observed_pids', ()))
        events = result['observation']['events']
        report.update(launcher_ok=result['ok'], launcher_error=result.get('error'), cleanup=result['cleanup'],
                      observer_installed=result['observation']['installed'], observer_removed=result['observation']['removed'],
                      job_kill_on_close=result.get('job_kill_on_close'), runner_exit_code=result['runner_exit_code'],
                      input_samples=len(result['input_samples']), input_changes=len(result['input_desktop_changes']),
                      desktop_switch_event=result['desktop_switch_observed'], elapsed_ms=result['lifecycle_ms'],
                      foreground_endpoints_equal=result.get('foreground_before') == result.get('foreground_after'),
                      focus_or_foreground_events=sum(e['event'] in ('foreground', 'focus') for e in events),
                      focus_or_foreground_events_known_job_pids=sum(e['pid'] in pids and e['event'] in ('foreground', 'focus') for e in events))
        require(temp.resolve(strict=True) == temp and os.path.samestat(stat, temp.stat()), 'temporary root changed')
    remaining = []
    for proc in psutil.process_iter(['name', 'create_time', 'ppid']):
        if (proc.info['name'] or '').lower() == 'qq.exe':
            remaining.append({'pid': proc.pid, 'ppid': proc.info['ppid'], 'create_time': proc.info['create_time']})
    report.update(temporary_root_removed=not temp.exists(), final_qq_process_count=len(remaining),
                  final_qq_processes=remaining)
    report['main_verified'] = report.get('page') == 'main_navigation' and LABELS[0] in report.get('fields', {})
    report['passed'] = bool(report.get('completed') and result['ok'] and report.get('worker_closed')
                            and report['temporary_root_removed'] and report['cleanup']['active_processes'] == 0
                            and report.get('native', {}).get('set_equal') and not report['focus_or_foreground_events_known_job_pids'])
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__mp_main__':
    worker_setup()
elif __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='allow one private desktop launch with the retained account')
    parser.add_argument('--job', help=argparse.SUPPRESS)
    parser.add_argument('--expected-desktop', help=argparse.SUPPRESS)
    parser.add_argument('--out', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    self_check()
    if args.live:
        if args.job:
            require(args.expected_desktop and args.out, 'use the private desktop launcher')
            raise SystemExit(child(args.expected_desktop, args.job, args.out))
        raise SystemExit(live())
    with tempfile.TemporaryDirectory(prefix='deskweft-qq-report-check-') as folder:
        path = Path(folder) / 'report.json'
        assert read_child(path)['completed'] is False
        for payload in (b'{', b'[]', b'null', b'\xff', b'{}'):
            path.write_bytes(payload)
            assert child('unused', 'unused', path) == 1 and path.read_bytes() == payload
            assert read_child(path).get('child_report_error')
    print('Self-check passed. Use --live for a real QQ run.')
