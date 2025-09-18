#include <iostream>
#include <cstdint>

using namespace std;

extern "C" __declspec( dllexport ) int64_t multiply(long a, int64_t b) {
    return a * b;
}

int main() {
    int64_t a;
    int64_t b;
    cout << "Enter a number: ";
    cin >> a;
    cout << "Enter another number: ";
    cin >> b;
    cout << "The product is " << multiply(a, b) << endl;
    return 0;
}