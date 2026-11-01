/* Host-only exact context checks against the pinned libsepol.
 * Opens only input files with rb/r; does not load any policy into a kernel. */
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sepol/policydb.h>
#include <sepol/context.h>

static int check(sepol_policydb_t *db, const char *text, int *parsed) {
    sepol_context_t *context = NULL;
    *parsed = sepol_context_from_string(NULL, text, &context);
    int result = *parsed ? -1 : sepol_context_check(NULL, db, context);
    sepol_context_free(context);
    return result;
}

int main(int argc, char **argv) {
    sepol_policydb_t *db = NULL;
    sepol_policy_file_t *policyfile = NULL;
    FILE *fp = NULL, *labels = NULL;
    char *line = NULL;
    size_t capacity = 0;
    int status = 2, parsed;
    if (argc != 3) { fprintf(stderr, "usage: check-contexts POLICY CONTEXTS\n"); return 2; }
    fp = fopen(argv[1], "rb"); labels = fopen(argv[2], "r");
    if (!fp || !labels || sepol_policydb_create(&db) || sepol_policy_file_create(&policyfile)) goto cleanup;
    sepol_policy_file_set_fp(policyfile, fp);
    if (sepol_policydb_read(db, policyfile)) goto cleanup;
    /* Positive/negative controls prevent a disabled or wrong-policy checker
     * from being reported as successful validation of every input. */
    if (check(db, "u:r:init:s0", &parsed) || parsed) goto cleanup;
    if (check(db, "u:object_r:system_file:s0", &parsed) || parsed) goto cleanup;
    if (check(db, "u:object_r:r8q_nonexistent_context_control:s0", &parsed) == 0 || parsed) goto cleanup;
    while (getline(&line, &capacity, labels) >= 0) {
        size_t n = strlen(line);
        while (n && (line[n-1]=='\r' || line[n-1]=='\n')) line[--n]='\0';
        if (!n || n > 4096 || strchr(line, '\t') || strchr(line, ' ')) goto cleanup;
        int result = check(db, line, &parsed);
        printf("%s\t%d\t%d\n", line, parsed, result);
    }
    if (ferror(labels) || fflush(stdout)) goto cleanup;
    status = 0;
cleanup:
    free(line);
    sepol_policy_file_free(policyfile); sepol_policydb_free(db);
    if (fp) fclose(fp);
    if (labels) fclose(labels);
    return status;
}
