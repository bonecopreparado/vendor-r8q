/* Host-only explanations for context checks against the exact loaded policy.
 * Uses the same pinned static libsepol as check_contexts.c; never loads a policy
 * into a kernel or changes a ROM image. -1 means an attribute was unavailable. */
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sepol/context.h>
#include <sepol/policydb.h>
#include <sepol/policydb/policydb.h>

static int member(policydb_t *p, type_datum_t *type, const char *name) {
    type_datum_t *attribute = hashtab_search(p->p_types.table, name);
    if (!attribute || attribute->flavor != TYPE_ATTRIB || !p->type_attr_map) return -1;
    if (!type) return 0;
    return ebitmap_get_bit(&p->type_attr_map[type->s.value - 1], attribute->s.value - 1);
}

int main(int argc, char **argv) {
    sepol_policydb_t *db = NULL;
    sepol_policy_file_t *policyfile = NULL;
    FILE *policy = NULL, *labels = NULL;
    char *line = NULL;
    size_t capacity = 0;
    int status = 2;
    if (argc != 3) { fprintf(stderr, "usage: check-context-traits POLICY CONTEXTS\n"); return 2; }
    policy = fopen(argv[1], "rb"); labels = fopen(argv[2], "r");
    if (!policy || !labels || sepol_policydb_create(&db) || sepol_policy_file_create(&policyfile)) goto cleanup;
    sepol_policy_file_set_fp(policyfile, policy);
    if (sepol_policydb_read(db, policyfile)) goto cleanup;
    while (getline(&line, &capacity, labels) >= 0) {
        size_t n = strlen(line);
        while (n && (line[n-1] == '\r' || line[n-1] == '\n')) line[--n] = '\0';
        if (!n || n > 4096 || strchr(line, '\t') || strchr(line, ' ')) goto cleanup;
        sepol_context_t *context = NULL;
        if (sepol_context_from_string(NULL, line, &context)) goto cleanup;
        policydb_t *p = &db->p;
        type_datum_t *type = hashtab_search(p->p_types.table, sepol_context_get_type(context));
        role_datum_t *role = hashtab_search(p->p_roles.table, sepol_context_get_role(context));
        user_datum_t *user = hashtab_search(p->p_users.table, sepol_context_get_user(context));
        int user_role = user && role ? ebitmap_get_bit(&user->cache, role->s.value-1) : 0;
        int role_type = role && type ? ebitmap_get_bit(&role->cache, type->s.value-1) : 0;
        printf("%s\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\n", line,
               type != NULL, role != NULL, user != NULL, user_role, role_type,
               member(p, type, "domain"), member(p, type, "appdomain"),
               member(p, type, "service_manager_type"));
        sepol_context_free(context);
    }
    if (ferror(labels) || fflush(stdout)) goto cleanup;
    status = 0;
cleanup:
    free(line);
    sepol_policy_file_free(policyfile); sepol_policydb_free(db);
    if (policy) fclose(policy);
    if (labels) fclose(labels);
    return status;
}
