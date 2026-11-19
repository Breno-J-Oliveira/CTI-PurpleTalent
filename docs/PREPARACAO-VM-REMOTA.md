# Laboratórios remotos

Para preparar outro computador, use o [guia de migração no Windows](MIGRAR-SERVIDOR-WINDOWS.md). Ele cobre cópia do runtime, instalação do zero, inicialização e troca de executor.

O site mantém o banco de candidatos. O executor no computador consulta a fila do site por HTTPS e inicia uma VM Ubuntu descartável em QEMU. A VM tem rede restrita e serve registros fictícios. A página do candidato só exibe os registros autorizados para a sua sessão. O cenário Incidente em andamento oferece registros sintéticos. Intranet esquecida usa uma auditoria fictícia de publicação de documentos, com catálogo, registro de publicação e referências próprias por VM.

## Fila compartilhada

Cada candidato pode ter uma reserva pendente ou em uso. A página do desafio atualiza a posição automaticamente e oferece o cancelamento enquanto a pessoa aguarda. O executor atende por ordem de chegada. Uma próxima VM só começa depois que o desligamento da anterior é confirmado.

A janela de 60 minutos começa quando a VM fica pronta. Uma reserva que aguardar mais de 24 horas, ou perder o vínculo com a equipe do desafio antes de ser atendida, é encerrada pela fila. A mentoria acompanha os nomes, os desafios e a situação em **Ambientes virtuais**. Cada candidato vê apenas a própria reserva.

Se o desligamento falhar, a próxima reserva fica aguardando. A pessoa que iniciou o ambiente pode pedir nova tentativa. Uma operação interrompida precisa de reconciliação do executor antes de a fila prosseguir.

## Preparação do executor

- Use os binários QEMU, imagem Ubuntu e pycdlib conferidos no runtime privado. Prepare localmente os wheels Linux x86-64 de Flask e suas dependências para o Python 3.12 do convidado. Não use diretórios compartilhados com candidatos.
- Mantenha o computador ligado. Reserve tempo para o boot por emulação. O executor atende uma VM por vez.
- Configure LAB_QEMU_RUNTIME com o caminho do runtime, LAB_QEMU_WHEELS com a pasta dos wheels, LAB_WORKER_SITE com a origem HTTPS do site e LAB_WORKER_JOURNAL com um caminho absoluto em pasta privada.
- Use um token aleatório longo e exclusivo. Configure LAB_WORKER_TOKEN no computador e o mesmo valor em REMOTE_WORKER_TOKEN na configuração privada do site. Mantenha os valores fora do Git e dos logs.
- Inicie com o Python do ambiente do projeto executando scripts/remote_worker.py.

## Ativação e verificação

Prepare uma cópia do banco e ensaie com contas fictícias. A inicialização app.init_db() adiciona as tabelas. Quando o executor estiver disponível e após validar em ambiente separado, habilite REMOTE_LABS_ENABLED=1 e REMOTE_RELAY_ENABLED=1 na configuração privada do site e reinicie o aplicativo.

Com uma conta de participante, abra Incidente em andamento ou Intranet esquecida. Solicite a VM, atualize a página e abra o laboratório. Consulte os registros fictícios e encerre a sessão. Confirme em segunda conta que os registros alheios permanecem inacessíveis e que o encerramento revoga o acesso.

Se houver falha durante uma operação, confira o journal, a fila e a VM antes de retomar. O executor recusa reinicialização se há uma VM anteriormente registrada em execução ou estado incerto. O encerramento normal do processo para a VM sob supervisão. Em caso de queda abrupta, um temporizador no convidado pode desligá-la após a inicialização. Confira o processo QEMU e a disponibilidade do disco no host antes de nova rodada.

A atualização do site publicado e a ativação dos laboratórios dependem de validação no ambiente escolhido.

Para atualizar o executor, encerre a sessão de laboratório e aguarde o desligamento. Pare o processo com Ctrl+C, atualize o código e inicie novamente usando a mesma configuração privada. Atualize o site antes de solicitar sessões no novo cenário.

## Verificação da fila

A suíte Python foi executada em seis grupos de testes. Foram 240 aprovações, com dois testes opcionais de VirtualBox legado ignorados. O ensaio local no Chrome usou dois candidatos e duas VMs reais de QEMU em sequência. Ambos consultaram registros das respectivas VMs e tiveram o desligamento confirmado. O teste incluiu atualização automática da posição, painel da mentoria, tempo restante e bloqueio de acesso de outra conta. A migração foi repetida duas vezes sobre uma cópia do banco anterior, com registros preservados.
