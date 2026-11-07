"""Stream one requested P1 ROM ZIP to GoFile; never hold its bytes in RAM."""
from pathlib import Path
import argparse,hashlib,json,os,re,subprocess,tempfile,urllib.parse

ROM_NAMES=frozenset(('HyperOS4-R8Q-P1-SINGLE-EXPERIMENTAL.zip',
                     'HyperOS4-R8Q-P1r1-SINGLE-EXPERIMENTAL.zip',
                     'HyperOS4-R8Q-P1r2-SINGLE-EXPERIMENTAL.zip'))

def validate_name(name):
    if name not in ROM_NAMES:raise ValueError('Only a reviewed P1/P1r1/P1r2 ROM ZIP name is accepted')

def identities(path):
    sha=hashlib.sha256();md5=hashlib.md5(usedforsecurity=False);size=0
    with path.open('rb') as stream:
        while data:=stream.read(4*1024**2):sha.update(data);md5.update(data);size+=len(data)
    return dict(bytes=size,sha256=sha.hexdigest(),md5=md5.hexdigest())

def public_result(response,path,before):
    if response.get('status')!='ok' or not isinstance(response.get('data'),dict):
        raise ValueError('GoFile did not confirm the upload; raw API responses are not logged')
    data=response['data'];url=data.get('downloadPage','');parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='https' or parsed.netloc!='gofile.io' or not re.fullmatch('/d/[A-Za-z0-9_-]{4,128}',parsed.path) or parsed.query or parsed.fragment:
        raise ValueError('GoFile returned an unexpected download link')
    if 'size' in data and (type(data['size'])is not int or data['size']!=before['bytes']):
        raise ValueError('Remote size does not match the local ZIP')
    if 'md5' in data and data['md5'].lower()!=before['md5']:
        raise ValueError('Remote transport MD5 does not match the local ZIP')
    return dict(name=path.name,size=before['bytes'],sha256=before['sha256'],download_page=url,
                remote_size_checked='size'in data,remote_md5_checked='md5'in data,
                status='EXPERIMENTAL_P1_NOT_BOOT_CONFIRMED')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('file',type=Path);ap.add_argument('--result',type=Path)
    ap.add_argument('--check-name-only',action='store_true',help='Validate the planned build name before reconstructing images; never uploads')
    args=ap.parse_args();path=args.file
    validate_name(path.name)
    if args.check_name_only:
        print('Reviewed ROM ZIP name accepted:',path.name)
        return
    if args.result is None:ap.error('--result is required for an upload')
    if path.is_symlink() or not path.is_file():
        raise ValueError('Only the generated regular ROM ZIP is accepted')
    path=path.resolve()
    if not re.fullmatch(r'[A-Za-z0-9_./@+-]+',str(path)):raise ValueError('Unsupported upload path')
    before=identities(path)
    if not 0<before['bytes']<=8*1024**3:raise ValueError('P1 ZIP is empty or exceeds 8 GiB')
    token=os.environ.get('GOFILE_TOKEN')
    if token and (len(token)>8192 or any(ord(c)<33 or ord(c)>126 for c in token)):
        raise ValueError('GOFILE_TOKEN format is invalid')
    with tempfile.TemporaryDirectory(prefix='p1-gofile-') as td:
        work=Path(td);config=work/'curl.conf';raw=work/'response.json'
        lines=['url = "https://upload.gofile.io/uploadfile"',
               'form = '+json.dumps('file=@'+str(path)+';filename='+path.name+';type=application/zip'),
               'header = "Accept: application/json"']
        if token:lines.append('header = '+json.dumps('Authorization: Bearer '+token))
        config.write_text('\n'.join(lines)+'\n');config.chmod(0o600)
        print('Uploading one experimental P1 ZIP:',before['bytes'],'bytes',flush=True)
        # curl streams multipart file data. Never print the private config or
        # raw response, which can contain the service's anonymous account token.
        run=subprocess.run(['curl','--config',str(config),'--silent','--show-error','--fail',
                            '--connect-timeout','30','--max-time','2400','--speed-time','120',
                            '--retry','2','--retry-delay','5','--retry-max-time','2400',
                            '--speed-limit','1024','--write-out','%{http_code}','--output',str(raw)],capture_output=True,timeout=2410)
        if run.returncode:
            status=getattr(run,'stdout',b'').decode('ascii',errors='ignore').strip()
            status=status if re.fullmatch(r'[0-9]{3}',status) else 'unknown'
            raise RuntimeError('Streaming GoFile upload failed (curl exit '+str(run.returncode)+', HTTP '+status+')')
        if raw.stat().st_size>1024**2:raise ValueError('GoFile response exceeds the expected bound')
        result=public_result(json.loads(raw.read_text()),path,before)
    if identities(path)!=before:raise ValueError('The local ZIP changed during upload')
    args.result.parent.mkdir(parents=True,exist_ok=True);args.result.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)
    summary=os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with Path(summary).open('a') as out:
            out.write('\nExperimental P1 single ZIP: ['+path.name+']('+result['download_page']+')\n\nSHA256: `'+result['sha256']+'`\n\nBoot not confirmed. Read build status and instructions before testing.\n')

if __name__=='__main__':main()
