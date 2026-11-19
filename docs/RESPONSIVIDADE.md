# Revisão de responsividade — 19/11/2026

Correções sobre a versão `885e531` de `Breno-J-Oliveira/salvamento`. A atualização da hospedagem PythonAnywhere é feita pelo responsável pelo site após receber o código.

## Correções

- Página inicial: colunas e cards de vagas respeitam a área disponível a partir de 320 px; a barra da captura permite abreviar seu título decorativo sem ampliar o layout.
- Faixa CTI: logo, texto e barras passam a uma coluna no celular, evitando texto espremido e elementos fora do card.
- Cabeçalho: marca, menu e ações ocupam posições explícitas no celular. Até 900 px, o cabeçalho acompanha a rolagem para que links do menu expandido continuem acessíveis na orientação horizontal.
- Administração: notas auxiliares dos editores de desafios e blog não invadem os campos. A explicação após o link do dossiê mantém espaço mesmo quando o link quebra em duas linhas.
- Chamada inicial: “Contrate talentos pelo que eles sabem fazer”. A versão dos assets foi atualizada para invalidar o cache dos estilos anteriores.

## Reproduzir a verificação

Na raiz do checkout, com Python/Flask e Playwright/Chrome disponíveis no ambiente de QA, inicie um servidor exclusivo:

```powershell
python tests/serve_responsive.py
```

Em outro terminal, na mesma pasta:

```powershell
node tests/browser_responsive.cjs
```

Se Playwright estiver fora do projeto, configure `NODE_PATH` para o diretório `node_modules` do ambiente de QA. Ele não é uma dependência do produto.

O servidor cria uma base fictícia nova em `output/qa/responsive`, na porta fixa 5058. Não usa o banco da equipe. A fila e o laboratório remoto são representados por registros sintéticos; nenhuma VM ou executor real é iniciado.

O roteiro verifica as rotas HTML de visitante, participante e mentor em 320, 375, 390, 768, 1024 e 1440 px, nos temas claro e escuro. Inclui desafios, vagas, candidatura/seleção, dossiê/rubrica, evolução, equipes, blog, editores, laboratório/fila e páginas de erro. APIs JSON não são tratadas como páginas.

Também verifica menus expandidos, foco por Enter/Escape, orientação horizontal, conteúdo cortado, formulários, busca, senha visível, tema persistido, prévia/reordenação local de perguntas e navegação sem JavaScript. Tabelas largas mantêm rolagem dentro de seu próprio contêiner.

Resultados JSON e capturas antes/depois ficam em `output/qa/responsive`, ignorados pelo Git. Use `RESPONSIVE_LABEL` para separar execuções; `RESPONSIVE_WIDTHS` e `RESPONSIVE_THEMES` permitem uma rodada dirigida.

## Evidências desta entrega

- `python tests/run_report.py`: 243 testes executados, 241 aprovados e 2 ignorados por dependerem do ambiente real de virtualização.
- Matriz Chrome: 981 verificações de página/tema, detalhes e menus, sem overflow, cortes de conteúdo ou sobreposição de cabeçalho detectados nas larguras testadas. Todas as rotas HTML inventariadas foram contempladas.
- Seis grupos funcionais adicionais aprovados: menus na horizontal; busca/senha/tema; editor de perguntas; alternativa sem JavaScript; espaçamento das notas e do link do dossiê; briefings de todos os desafios. Este último percorreu 34 briefings desbloqueados, em três larguras e dois temas (204 verificações adicionais).
- Revisão independente: 33 verificações de espaçamento aprovadas em 320/375/768 px e conferência dos cabeçalhos nos limites entre breakpoints.
- Templates Jinja compilados, sintaxe do JavaScript e Python de QA verificadas. Nenhum erro JavaScript ou asset ausente foi registrado no percurso de navegador.

As contagens de layout incluem a mesma tela em vários tamanhos e temas; não representam 981 funcionalidades distintas. Capturas `before-*`, `final-*` e `review-*` e os respectivos JSON ficam no diretório local de evidências citado acima.

## Limites

Verificação em Chrome automatizado com dados fictícios. Não substitui testes em Safari/iPhone físico, leitor de tela ou nova validação após atualizar a hospedagem. O laboratório foi verificado como interface; não houve boot real de VM nesta revisão.
