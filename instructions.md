# Instructions

- Prepare ambiente para realizar benchmarks do FedShop (./reference-repos/FedShop/).
    - Explore o repositório
    - Gere scripts simples (bash) que permitam replicar facilmente o benchmarks, caso não já exista.
    - Os scripts devem contemplar todas as query engines usadas e testes descritos no artigo.
    - Gere um guia no AGENTS.md, rules, SKILLS.md se necessário e outros recursos para persistir o contexto armazenado.
    - Clone o restante dos repositórios necessários das query engines usadas (use o repositório atualizado de cada uma no lugar da versão fixada como submodule no FedShop).

- Objetivo: Baseado no artigo (./reference-papers/fedshop.pdf), vou desenvolver uma engine mínima em Golang no diretório atual (./).
    - Ela deve integrar as melhorias descritas em cada uma das query engines no artigo base (não precisa ser todas, desde que seja viável).
    - Deve ser o mínimo viável e, para criá-la, devo em basear no source code das outras engines que você irá clonar
