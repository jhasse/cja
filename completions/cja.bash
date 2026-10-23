# bash completion for cja                                  -*- shell-script -*-

# Configured build directories, from the <build-dir>.ninja manifests that cja
# writes to the project root
_comp_cmd_cja__build_dirs()
{
    local f
    for f in *.ninja; do
        [[ -f $f ]] && printf '%s\n' "${f%.ninja}"
    done
}

# Targets worth building by name: phony targets, libraries, executables and
# custom commands, but not object files and other intermediate outputs
_comp_cmd_cja__targets()
{
    local line
    [[ -f $1 ]] || return
    ninja -f "$1" -t targets all 2>/dev/null | while IFS= read -r line; do
        case ${line##*: } in
            phony | ar | link | link_cxx | solink | solink_cxx | custom_command)
                printf '%s\n' "${line%: *}"
                ;;
        esac
    done
}

_comp_cmd_cja()
{
    local cur prev words cword split
    _init_completion -s || return

    local i subcommand="" build_dir="" release=""
    for ((i = 1; i < cword; i++)); do
        case ${words[i]} in
            -E)
                # Everything after -E belongs to the command
                if ((cword == i + 1)); then
                    COMPREPLY=($(compgen -W "make_directory touch copy
                        copy_if_different" -- "$cur"))
                else
                    _filedir
                fi
                return
                ;;
            -P)
                # Everything after -P SCRIPT is passed to the script
                if ((cword == i + 1)); then
                    _filedir cmake
                else
                    _filedir
                fi
                return
                ;;
            -B | --build-dir)
                build_dir=${words[i + 1]}
                ((i++))
                ;;
            --build-dir=*)
                build_dir=${words[i]#*=}
                ;;
            -D | --assume-filename | --lines | -j | -l)
                ((i++))
                ;;
            --release)
                release=1
                ;;
            build | test | run | format | lsp)
                [[ -z $subcommand ]] && subcommand=${words[i]}
                ;;
        esac
    done

    case $prev in
        -B | --build-dir)
            COMPREPLY=($(compgen -W "$(_comp_cmd_cja__build_dirs)" -- "$cur"))
            return
            ;;
        --assume-filename)
            _filedir
            return
            ;;
        -D | --lines | -j | -l)
            return
            ;;
    esac

    $split && return

    if [[ $cur == -* ]]; then
        local opts
        case $subcommand in
            "")
                opts="--help --version -B --build-dir -D --trace --strict --quiet
                    --release -E -P"
                ;;
            build)
                # -j, -k, -l, -n and -v are passed on to ninja
                opts="--help --release -B --build-dir -D -j -k -l -n -v"
                ;;
            test)
                opts="--help --release -B --build-dir -D --parallel -j -k -l -n -v"
                ;;
            run)
                opts="--help --release -B --build-dir -D"
                ;;
            format)
                opts="--help -i --in-place --check --assume-filename --lines"
                ;;
            lsp)
                opts="--help --stdio"
                ;;
        esac
        COMPREPLY=($(compgen -W "$opts" -- "$cur"))
        return
    fi

    case $subcommand in
        "")
            COMPREPLY=($(compgen -W "build test run format lsp" -- "$cur"))
            ;;
        build)
            if [[ -z $build_dir ]]; then
                build_dir=build${release:+-release}
            fi
            COMPREPLY=($(compgen -W "$(_comp_cmd_cja__targets "$build_dir.ninja")" \
                -- "$cur"))
            ;;
        run)
            # Arguments for the executable
            _filedir
            ;;
        format)
            _filedir 'cmake|txt'
            ;;
    esac
} &&
    complete -F _comp_cmd_cja cja

# ex: filetype=sh
