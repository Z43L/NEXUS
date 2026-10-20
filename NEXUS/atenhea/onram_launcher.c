#define _XOPEN_SOURCE 700
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#ifdef __APPLE__
#include <mach-o/dyld.h>
#endif

static int executable(const char *path) {
    return access(path, X_OK) == 0;
}

int main(int argc, char **argv) {
    char binary_path[PATH_MAX];
    char cli_path[PATH_MAX];
    char python_path[PATH_MAX];
    char *resolved;
    char *build_dir_end;
    char *repo_dir_end;
    const char *configured_python = getenv("ONRAM_PYTHON");
    const char *python = "python3";

    const char *executable_path = argv[0];
#ifdef __APPLE__
    char native_path[PATH_MAX];
    uint32_t native_path_size = sizeof(native_path);
    if (_NSGetExecutablePath(native_path, &native_path_size) != 0) {
        fprintf(stderr, "atenhea: executable path is too long\n");
        return 127;
    }
    executable_path = native_path;
#endif
    if (realpath(executable_path, binary_path) == NULL) {
        fprintf(stderr, "atenhea: cannot resolve executable path: %s\n", strerror(errno));
        return 127;
    }
    resolved = strrchr(binary_path, '/');
    if (resolved == NULL) {
        fprintf(stderr, "atenhea: executable path has no directory\n");
        return 127;
    }
    *resolved = '\0'; /* build/ */
    build_dir_end = strrchr(binary_path, '/');
    if (build_dir_end == NULL) {
        fprintf(stderr, "atenhea: cannot find repository directory\n");
        return 127;
    }
    *build_dir_end = '\0'; /* third_party/ongram/ */
    repo_dir_end = strrchr(binary_path, '/');
    if (repo_dir_end == NULL || snprintf(cli_path, sizeof(cli_path), "%s/onram_cli.py", binary_path) >= (int)sizeof(cli_path)) {
        fprintf(stderr, "atenhea: cannot locate onram_cli.py\n");
        return 127;
    }
    if (access(cli_path, R_OK) != 0) {
        fprintf(stderr, "atenhea: CLI module is missing: %s\n", cli_path);
        return 127;
    }

    if (configured_python && *configured_python) {
        python = configured_python;
    } else if (snprintf(python_path, sizeof(python_path), "%s/.venv/bin/python", binary_path) < (int)sizeof(python_path) && executable(python_path)) {
        python = python_path;
    } else if (repo_dir_end && snprintf(python_path, sizeof(python_path), "%s/../../.venv-gemma4/bin/python", binary_path) < (int)sizeof(python_path) && executable(python_path)) {
        python = python_path;
    }

    char **child_argv = calloc((size_t)argc + 2, sizeof(char *));
    if (child_argv == NULL) {
        fprintf(stderr, "atenhea: out of memory\n");
        return 127;
    }
    child_argv[0] = (char *)python;
    child_argv[1] = cli_path;
    for (int i = 1; i < argc; ++i) {
        child_argv[i + 1] = argv[i];
    }
    child_argv[argc + 1] = NULL;
    execvp(python, child_argv);
    fprintf(stderr, "atenhea: cannot execute Python runtime '%s': %s\n", python, strerror(errno));
    free(child_argv);
    return 127;
}
