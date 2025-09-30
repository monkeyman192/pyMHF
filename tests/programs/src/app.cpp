#include <iostream>
#include <cstdint>

using namespace std;

extern "C" __declspec( dllexport ) int64_t multiply(long a, int64_t b) {
    return a * b;
}

int main(int argc, char* argv[]) {
    if (argc != 3) {
        cout << "Please enter 2 numbers to multiply" << endl;
        return 1;
    }
    int64_t a = atoi(argv[1]);
    int64_t b = atoi(argv[2]);
    cout << "The product is " << multiply(a, b) << endl;
    return 0;
}