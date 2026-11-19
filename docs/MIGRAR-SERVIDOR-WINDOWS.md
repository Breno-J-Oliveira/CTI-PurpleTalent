# Trocar o computador do Purple Talent

Este guia usa Windows x64, PowerShell, Python 3.12, Git e QEMU. O endereço público continua no PythonAnywhere. O computador novo executa os laboratórios e pode abrir uma cópia local do site para testes. Não precisa de Docker.

| Onde | O que fica |
| --- | --- |
| PythonAnywhere | Site público, banco de vagas e candidatos, chave da aplicação e configuração privada. |
| Computador novo | Código do GitHub, ambiente Python, executor QEMU e arquivos para iniciar as VMs. |
| Backup privado | Cópias do banco e dos arquivos do executor. Mantenha o token em um gerenciador de senhas. |

## 1. Preparar o computador novo

Instale o [Python para Windows](https://www.python.org/downloads/windows/) e o [Git para Windows](https://git-scm.com/download/win). Confirme que `py -3.12 --version` e `git --version` funcionam num PowerShell novo. Separe alguns GB de disco para a imagem e os discos descartáveis. Cada VM recebe 1 GiB de RAM, além do consumo do Windows e do QEMU.

```powershell
Set-Location $HOME
git clone https://github.com/Breno-J-Oliveira/CTI-PurpleTalent.git purple-talent
Set-Location "$HOME\purple-talent"
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
git rev-parse --short HEAD
$Runtime = Join-Path $env:LOCALAPPDATA 'PurpleTalent\runtime'
New-Item -ItemType Directory -Path $Runtime -Force | Out-Null
```

Se já houver um clone, use `git pull --ff-only` dentro dele. Use um diretório privado fora do projeto e do OneDrive para o runtime. Você pode trocar `$Runtime` por um caminho absoluto em outro disco.

## 2. Levar o runtime das VMs

O caminho mais rápido é copiar os arquivos que já funcionam no computador antigo. Na instalação anterior, a imagem e o QEMU ficavam em `D:\purple-talent-runtime` e os wheels em `D:\purple-talent-qa\qemu-http\wheels`. No computador novo, organize assim:

```text
runtime/
  ubuntu-base.img
  qemu/          (pasta inteira, com os executáveis, DLLs e firmware)
  tools/lib/     (pycdlib)
  wheels/        (Flask e dependências para Linux x86-64 e Python 3.12)
```

Copie a imagem-base com o mesmo nome e compare o SHA-256 nas duas máquinas. Use o comando abaixo em cada uma com seu respectivo caminho:

```powershell
Get-FileHash -Algorithm SHA256 (Join-Path $Runtime 'ubuntu-base.img')
```

Deixe as pastas `incident-*`, os discos de sessão, os logs, o journal em uso e o arquivo de lock no computador antigo. Na troca ordenada, o computador novo inicia com seu próprio journal. O journal antigo fica disponível para diagnóstico ou retorno ao computador anterior.

### Preparar os arquivos do zero

1. Instale o QEMU x64 e copie a pasta completa da instalação para `runtime\qemu`. Confira que `qemu-system-x86_64.exe` e `qemu-img.exe` estão diretamente dentro dela. [Downloads do QEMU](https://www.qemu.org/download/#windows)
2. Baixe `noble-server-cloudimg-amd64.img` e a lista `SHA256SUMS` do mesmo diretório oficial. Confirme que o hash do arquivo corresponde à linha da imagem amd64. Coloque a imagem conferida em `runtime\ubuntu-base.img`. Preserve o arquivo-base para reutilizar entre execuções. [Imagens Ubuntu 24.04](https://cloud-images.ubuntu.com/noble/current/)
3. Ainda na pasta do projeto, instale o pycdlib no runtime e baixe os wheels para o sistema convidado.

```powershell
.\.venv\Scripts\python.exe -m pip install --target (Join-Path $Runtime 'tools\lib') pycdlib==1.14.0
.\.venv\Scripts\python.exe -m pip download --dest (Join-Path $Runtime 'wheels') `
  --only-binary=:all: --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 `
  --platform manylinux_2_28_x86_64 --implementation cp --python-version 3.12 --abi cp312 Flask==3.1.3
```

O alvo dos wheels é o Ubuntu na VM. O Python do host Windows instala suas dependências usando `requirements.txt`. [Opções de download do pip](https://pip.pypa.io/en/stable/cli/pip_download/)

## 3. Testar e fazer a troca

No computador novo, faça a checagem local antes de desligar o antigo:

```powershell
$Site = 'https://brenooliveira123.pythonanywhere.com'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_remote_worker.ps1 -Site $Site -Runtime $Runtime -CheckOnly
```

A checagem valida os arquivos locais e o formato da imagem. Ela dispensa o token e não entra na fila. A política de execução do exemplo vale apenas para esse processo do PowerShell.

1. Combine uma janela sem novos testes. No site, confira **Mentoria → Ambientes virtuais**. Peça aos participantes que encerrem os ambientes ou saiam da fila. Aguarde a confirmação do desligamento. Se a VM ainda estiver iniciando, o executor processa o pedido depois que o boot responde ou expira.
2. No computador antigo, pressione **Ctrl+C** no console do executor. Confirme que o console voltou ao prompt e que a VM do Purple Talent saiu. Mantenha os arquivos antigos para retorno. Rode um único executor para o mesmo site.
3. No computador novo, execute o comando abaixo e cole no prompt o token do executor que já corresponde a `REMOTE_WORKER_TOKEN` na configuração privada do PythonAnywhere. A entrada é mascarada. A mudança de computador pode reutilizar a configuração do site e o token existente. Caso o token tenha sido perdido, planeje a troca com quem administra a hospedagem.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_remote_worker.ps1 -Site $Site -Runtime $Runtime
```

O script usa `runtime\worker.db` como journal. Para caminhos personalizados, passe `-Wheels 'D:\runtime\wheels'` ou `-Journal 'D:\runtime\worker.db'`. Mantenha a janela aberta e o computador ligado, sem suspensão durante os testes. O executor faz conexões de saída por HTTPS. A VM fica ligada ao loopback do computador. Dispensa abrir portas no roteador.

4. No site público, use uma conta fictícia para abrir **Intranet esquecida** e pedir ambiente. Aguarde **Ambiente pronto**, abra o laboratório, carregue o catálogo e encerre. Confirme que o acesso some e que a fila libera a vaga. Repita com **Incidente em andamento** e confira a mentoria. O tempo de prova conta a partir de **Ambiente pronto**.

| Sintoma | O que conferir |
| --- | --- |
| A fila não anda | Console aberto no computador novo, origem HTTPS exata, token correspondente e flags `REMOTE_LABS_ENABLED` e `REMOTE_RELAY_ENABLED` ativadas no site. |
| A VM fica iniciando | Espaço de disco, RAM livre e `qemu.err` da pasta da sessão. O boot por emulação pode levar vários minutos. |
| O encerramento não foi confirmado | Verifique a fila, o processo QEMU e o journal no computador que iniciou a VM. Preserve o journal até reconciliar a sessão. |
| Precisa voltar ao computador antigo | Encerre as sessões no novo, pare seu executor e volte a iniciar o antigo com sua configuração privada. Confirme a fila antes de reabrir o uso. |

Para trocar o computador do executor, não é necessário dar Reload no PythonAnywhere. Consulte a [hospedagem](HOSPEDAGEM.md) caso as variáveis da aplicação precisem ser alteradas.

## 4. Rodar uma cópia local do site

No PowerShell do computador novo, dentro da pasta do projeto:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_local.ps1 -Demo -Port 5057
```

Abra [a demonstração local](http://127.0.0.1:5057). Esse modo prepara dados fictícios separados do banco de trabalho. Para rodar com banco local próprio, remova `-Demo` e abra [a porta padrão](http://127.0.0.1:5000):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_local.ps1
```

Se você precisa levar **também um banco local antigo**, faça o backup abaixo na pasta do projeto **do computador antigo**. Troque `lab.db` pelo caminho real mostrado no console. Use arquivos de destino novos.

```powershell
$BackupFolder = Join-Path $env:LOCALAPPDATA 'PurpleTalent\backup'
New-Item -ItemType Directory -Path $BackupFolder -Force | Out-Null
$BackupFile = Join-Path $BackupFolder ('lab-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.db')
.\.venv\Scripts\python.exe .\scripts\backup_database.py backup .\lab.db $BackupFile
```

Transfira a cópia para uma pasta privada no computador novo. No exemplo abaixo, substitua `lab-copiado.db` pelo nome da cópia transportada:

```powershell
$Private = Join-Path $env:LOCALAPPDATA 'PurpleTalent'
New-Item -ItemType Directory -Path $Private -Force | Out-Null
$LocalDb = Join-Path $Private 'lab-restaurado.db'
.\.venv\Scripts\python.exe .\scripts\backup_database.py restore (Join-Path $Private 'lab-copiado.db') $LocalDb
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_local.ps1 -Database $LocalDb
```

O site local escuta em `127.0.0.1` e serve para testes no próprio computador. A migração do banco local não afeta os cadastros públicos. Os laboratórios do site publicado usam o **executor QEMU** da seção anterior. Caso queira testar os laboratórios no modo legado do site local, veja [VirtualBox](VIRTUALBOX.md).
