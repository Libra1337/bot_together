typedef struct napi_module napi_module;

extern void napi_module_register(napi_module *mod);

void qq_magic_napi_register(napi_module *mod) {
  napi_module_register(mod);
}
