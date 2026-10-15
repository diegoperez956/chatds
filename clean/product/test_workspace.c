/* SPDX-License-Identifier: MIT
 * Host-only allocator/borrow probe. Include the actual loader so required
 * bytes cannot drift from its private arena check; never change a card model.
 * Optional argv[1] loads a real DSQ8 model instead of the synthetic shape. */
#include <assert.h>
#include <stdlib.h>
#include "learned.c"

static void probe(const chatds_model *m, unsigned context) {
    const chatds_model_config *c = &m->config;
    size_t calculated = (size_t)c->layers * context * c->kv_heads *
        (c->dim / c->heads) * sizeof(int16_t);
    int16_t *keys = calloc(1, calculated);
    assert(keys);
    chatds_session_options options = {0}; options.context_length = context;
    chatds_session *s = NULL;
    assert(chatds_session_create_with_keys(m, &options, keys, calculated, &s) == CHATDS_OK);
    chatds_session_info info;
    chatds_session_get_info(s, &info);
    size_t required = BLOB_BYTES + sizeof(cds_router_work);
    assert(info.kv_bytes / 2 == calculated);
    assert(info.external_key_bytes == calculated);
    assert(BLOB_BYTES == 39336 && sizeof(cds_router_work) == 10112 && required == 49448);
    int rc = c24_models_init(s, "./"); /* checks capacity; no head files read */
    assert(rc == (calculated < required ? -1 : 0));
    printf("context=%u value_bytes=%zu kv_bytes=%zu external_key_bytes=%zu "
           "head_bytes=%u scratch_bytes=%zu required_bytes=%zu shortfall=%zu init=%d\n",
           context, calculated, info.kv_bytes, info.external_key_bytes,
           BLOB_BYTES, sizeof(cds_router_work), required,
           calculated < required ? required - calculated : 0, rc);
    c24_models_invalidate(s);
    chatds_session_destroy(s);
    free(keys);
}

int main(int argc, char **argv) {
    chatds_model synthetic = {0}, *loaded_model = NULL;
    synthetic.config.dim = 192; synthetic.config.hidden_dim = 512;
    synthetic.config.layers = 6; synthetic.config.heads = 6;
    synthetic.config.kv_heads = 2; synthetic.config.vocab_size = 2048;
    synthetic.config.context_length = 256; synthetic.head_size = 32;
    synthetic.kv_dim = 64;
    const chatds_model *m = &synthetic;
    if (argc == 2) {
        assert(chatds_model_load(argv[1], &loaded_model) == CHATDS_OK);
        m = loaded_model;
    } else assert(argc == 1);
    assert(m->config.dim == 192 && m->config.layers == 6 &&
           m->config.heads == 6 && m->config.kv_heads == 2 &&
           m->config.context_length == 256);
    probe(m, 256);
    probe(m, 64); /* separate hypothetical session, not a production change */
    chatds_model_destroy(loaded_model);
    return 0;
}
