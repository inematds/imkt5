# MEMORY — Fatos de bootstrap

Seeds iniciais de memória carregados na primeira execução deste tenant.
Depois disso, a memória vive no SQLite e este arquivo deixa de ser autoritativo.

Formato livre. Cada bloco vira uma entrada `fact` / `preference` no
`MemoryStore` na inicialização.
