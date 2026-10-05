cmake_minimum_required(VERSION 3.10)
project(openssl_example C)

# Uses the bundled FindOpenSSL.cmake. Point OPENSSL_ROOT_DIR at your install
# if it isn't found automatically, e.g.:
#   cja build -DOPENSSL_ROOT_DIR=C:/Program\ Files/OpenSSL-Win64
find_package(OpenSSL 1.1.1 REQUIRED)

message(STATUS "Found OpenSSL ${OPENSSL_VERSION}")

add_executable(app main.c)
target_link_libraries(app PRIVATE OpenSSL::SSL OpenSSL::Crypto)
