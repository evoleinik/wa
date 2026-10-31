// wa-launch: the one program on the Mac that holds Full Disk Access for wa.
//
// macOS checks Full Disk Access against the "responsible" process. Over SSH that is
// sshd-keygen-wrapper, so a grant there covers every SSH login. wa-launch instead
// re-executes itself with responsibility disclaimed, which makes it its own responsible
// process. Then it runs one fixed, root-owned copy of wa, and macOS checks wa-launch's
// grant. Nothing else needs one.
//
//   wa-launch <wa arguments...>          for example: wa-launch chats --unread --json
//
// Walls:
// - The wa script path is fixed at build time.
// - The script and every folder above it must be owned by root, writable only by root,
//   and not symlinks. Otherwise anyone running as you could swap the code it runs.
// - Python gets a cleared environment and -I, so no variable steers it.
// - -o is refused, so the granted process never writes files into protected folders.
// Exit 3 for its own failures (wa's "cannot read" code), 2 for a refused argument.
//
// responsibility_spawnattrs_setdisclaim is exported by libsystem but not documented.
// If a macOS update breaks it, macOS denies access and wa exits 3. It fails closed.
//
// Build and install: launcher/install.sh

#include <limits.h>
#include <mach-o/dyld.h>
#include <pwd.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

#ifndef WA_SCRIPT
#define WA_SCRIPT "/usr/local/libexec/wa/wa"
#endif
#ifndef WA_PYTHON
#define WA_PYTHON "/usr/bin/python3"
#endif
#define DISCLAIMED "--wa-launch-disclaimed"

int responsibility_spawnattrs_setdisclaim(posix_spawnattr_t *attrs, int disclaim);

static volatile pid_t child_pid = 0;

static int fail(int code, const char *msg, const char *detail) {
    fprintf(stderr, "wa-launch: %s%s%s\n", msg, detail ? ": " : "", detail ? detail : "");
    return code;
}

static void forward(int sig) {
    if (child_pid > 0) kill(child_pid, sig);
}

static int own_path(char *out) {
    char buf[PATH_MAX];
    uint32_t size = sizeof buf;
    return _NSGetExecutablePath(buf, &size) == 0 && realpath(buf, out) != NULL;
}

// Returns 1 when path and every folder above it are root-owned, not group- or
// world-writable, and not symlinks. Otherwise copies the first bad path into bad.
static int root_owned_path(const char *path, char *bad, size_t badlen) {
    char buf[PATH_MAX];
    if (path[0] != '/' || strlen(path) >= sizeof buf) {
        snprintf(bad, badlen, "%s", path);
        return 0;
    }
    strcpy(buf, path);
    for (;;) {
        const char *check = buf[0] ? buf : "/";
        struct stat st;
        if (lstat(check, &st) != 0 || S_ISLNK(st.st_mode) || st.st_uid != 0 ||
            (st.st_mode & 022)) {
            snprintf(bad, badlen, "%s", check);
            return 0;
        }
        if (!buf[0]) return 1;
        *strrchr(buf, '/') = '\0';
    }
}

int main(int argc, char **argv) {
    char self[PATH_MAX], bad[PATH_MAX];
    for (int i = 1; i < argc; i++)
        if (strncmp(argv[i], "-o", 2) == 0)
            return fail(2, "-o is refused here, so the granted process never writes files",
                        "drop -o; wa saves media on the machine you run it from");
    if (!root_owned_path(WA_SCRIPT, bad, sizeof bad))
        return fail(3, "refusing to run, because this is missing or not owned and writable "
                       "only by root", bad);
    if (!own_path(self))
        return fail(3, "cannot find its own path", NULL);

    if (argc < 2 || strcmp(argv[1], DISCLAIMED) != 0) {
        // Step 1: run this same binary again in place, with responsibility disclaimed.
        char **args = calloc((size_t)argc + 2, sizeof *args);
        char *noenv[] = {NULL};
        posix_spawnattr_t attr;
        if (!args) return fail(3, "out of memory", NULL);
        args[0] = self;
        args[1] = DISCLAIMED;
        for (int i = 1; i < argc; i++) args[i + 1] = argv[i];
        posix_spawnattr_init(&attr);
        posix_spawnattr_setflags(&attr, POSIX_SPAWN_SETEXEC);
        if (responsibility_spawnattrs_setdisclaim(&attr, 1) != 0)
            return fail(3, "macOS refused to disclaim responsibility", NULL);
        int rc = posix_spawn(NULL, self, NULL, &attr, args, noenv);
        return fail(3, "cannot re-execute itself", strerror(rc));  // only on failure
    }

    // Step 2: now our own responsible process. Python inherits that, so macOS checks
    // this binary's grant.
    struct passwd *pw = getpwuid(getuid());
    if (!pw || !pw->pw_dir) return fail(3, "cannot find the home folder", NULL);
    char home[PATH_MAX + 8], user[300], launcher[PATH_MAX + 16];
    snprintf(home, sizeof home, "HOME=%s", pw->pw_dir);
    snprintf(user, sizeof user, "USER=%s", pw->pw_name);
    snprintf(launcher, sizeof launcher, "WA_LAUNCHER=%s", self);  // names the grant in hints
    char *env[] = {home, user, "PATH=/usr/bin:/bin:/usr/sbin:/sbin", "LANG=en_US.UTF-8",
                   "WA_LOCAL=1", "WA_NOLOG=1", launcher, NULL};

    char **args = calloc((size_t)argc + 2, sizeof *args);
    if (!args) return fail(3, "out of memory", NULL);
    args[0] = WA_PYTHON;
    args[1] = "-I";
    args[2] = WA_SCRIPT;
    for (int i = 2; i < argc; i++) args[i + 1] = argv[i];

    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = forward;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGHUP, &sa, NULL);

    pid_t pid;
    int rc = posix_spawn(&pid, WA_PYTHON, NULL, NULL, args, env);
    if (rc != 0) return fail(3, "cannot start " WA_PYTHON, strerror(rc));
    child_pid = pid;
    int status = 0;
    while (waitpid(pid, &status, 0) < 0)
        if (errno != EINTR) return fail(3, "lost the wa process", strerror(errno));
    if (WIFEXITED(status)) return WEXITSTATUS(status);
    if (WIFSIGNALED(status)) return 128 + WTERMSIG(status);
    return 3;
}
