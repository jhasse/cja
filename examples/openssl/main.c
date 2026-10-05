#include <openssl/evp.h>
#include <openssl/opensslv.h>
#include <openssl/ssl.h>

#include <stdio.h>
#include <string.h>

int main(void) {
    const char* message = "hello cja";
    unsigned char digest[EVP_MAX_MD_SIZE];
    unsigned int digest_length = 0;

    EVP_MD_CTX* context = EVP_MD_CTX_new();
    if (context == NULL ||
        EVP_DigestInit_ex(context, EVP_sha256(), NULL) != 1 ||
        EVP_DigestUpdate(context, message, strlen(message)) != 1 ||
        EVP_DigestFinal_ex(context, digest, &digest_length) != 1) {
        fprintf(stderr, "SHA-256 failed\n");
        EVP_MD_CTX_free(context);
        return 1;
    }
    EVP_MD_CTX_free(context);

    printf("%s\n", OpenSSL_version(OPENSSL_VERSION));
    printf("sha256(\"%s\") = ", message);
    for (unsigned int i = 0; i < digest_length; ++i) {
        printf("%02x", digest[i]);
    }
    printf("\n");

    SSL_CTX* ssl_context = SSL_CTX_new(TLS_client_method());
    printf("TLS client context: %s\n", ssl_context ? "ok" : "failed");
    SSL_CTX_free(ssl_context);
    return 0;
}
