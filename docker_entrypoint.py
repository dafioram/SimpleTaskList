"""Container entrypoint: fix data-folder ownership, then drop root and run the command.

Older versions of this image ran as root, so an existing ./data folder on the host
may be owned by root. When started as root, this makes the folder writable by the
unprivileged 'app' user and then switches to that user before starting gunicorn.
"""
import os
import pwd
import sys

DATA_DIR = '/app/data'
USER = 'app'


def main():
    cmd = sys.argv[1:] or ['gunicorn', '-c', 'gunicorn.conf.py']

    if os.geteuid() == 0:
        pw = pwd.getpwnam(USER)
        os.makedirs(DATA_DIR, exist_ok=True)
        for root, dirs, files in os.walk(DATA_DIR):
            for name in [root] + [os.path.join(root, n) for n in dirs + files]:
                st = os.lstat(name)
                if (st.st_uid, st.st_gid) != (pw.pw_uid, pw.pw_gid):
                    os.lchown(name, pw.pw_uid, pw.pw_gid)
        os.setgroups([])
        os.setgid(pw.pw_gid)
        os.setuid(pw.pw_uid)
        os.environ['HOME'] = pw.pw_dir
        os.environ['USER'] = USER

    os.execvp(cmd[0], cmd)


if __name__ == '__main__':
    main()
