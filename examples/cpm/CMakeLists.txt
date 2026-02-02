include(cmake/CPM.cmake)
CPMAddPackage(NAME libogg
    URL http://downloads.xiph.org/releases/ogg/libogg-1.3.5.tar.xz
    URL_HASH SHA256=c4d91be36fc8e54deae7575241e03f4211eb102afb3fc0775fbbc1b740016705
    OPTIONS "BUILD_TESTING OFF")
