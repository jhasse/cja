#include <QCoreApplication>
#include <cstdio>

int main(int argc, char *argv[]) {
    QCoreApplication app(argc, argv);
    std::printf("Hello from Qt %s\n", qVersion());
    return 0;
}
