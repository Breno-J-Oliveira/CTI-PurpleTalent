# Laboratórios remotos

O site mantém o banco de candidatos. O executor no computador consulta a fila do site por HTTPS e inicia uma VM Ubuntu descartável em QEMU. A VM tem rede restrita e serve registros fictícios. A página do candidato só exibe os registros autorizados para a sua sessão. O cenário Incidente em andamento oferece registros sintéticos. Intranet esquecida usa uma auditoria fictícia de publicação de documentos, com catálogo, registro de publicação e referências próprias por VM.

## Preparação do executor

- Use os binários QEMU, imagem Ubuntu e pycdlib conferidos no runtime privado. Prepare localmente os wheels Linux x86-64 de Flask e suas dependências para o Python 3.12 do convidado. Não use diretórios compartilhados com candidatos.
- Mantenha o computador ligado. Reserve tempo para o boot por emulação. O executor atende uma VM por vez.
- Configure LAB_QEMU_RUNTIME com o caminho do runtime, LAB_QEMU_WHEELS com a pasta dos wheels, LAB_WORKER_SITE com a origem HTTPS do site e LAB_WORKER_JOURNAL com um caminho absoluto em pasta privada.
- Use um token aleatório longo e exclusivo. Configure LAB_WORKER_TOKEN no computador e o mesmo valor em REMOTE_WORKER_TOKEN na configuração privada do site. Mantenha os valores fora do Git e dos logs.
- Inicie com o Python do ambiente do projeto executando scripts/remote_worker.py.

## Ativação e verificação

Prepare uma cópia do banco e ensaie com contas fictícias. A inicialização app.init_db() adiciona as tabelas. Quando o executor estiver disponível e após validar em ambiente separado, habilite REMOTE_LABS_ENABLED=1 e REMOTE_RELAY_ENABLED=1 na configuração privada do site e reinicie o aplicativo.

Abra Incidente em andamento com uma conta Blue Team, ou Intranet esquecida com uma conta Red Team. Solicite a VM, atualize a página e abra o laboratório. Consulte cada seção, envie a resposta na tela do desafio e encerre a sessão. Confirme em segunda conta que os registros alheios permanecem inacessíveis e que o encerramento revoga o acesso.

Se houver falha durante uma operação, confira o journal, a fila e a VM antes de retomar. O executor recusa reinicialização se há uma VM anteriormente registrada em execução ou estado incerto. O encerramento normal do processo para a VM sob supervisão. Em caso de queda abrupta, um temporizador no convidado pode desligá-la após a inicialização. Confira o processo QEMU e a disponibilidade do disco no host antes de nova rodada.

A atualização do site publicado e a ativação dos laboratórios dependem de validação no ambiente escolhido.

Para atualizar o executor, encerre a sessão de laboratório e aguarde o desligamento. Pare o processo com Ctrl+C, atualize o código e inicie novamente usando a mesma configuração privada. Atualize o site antes de solicitar sessões no novo cenário.
