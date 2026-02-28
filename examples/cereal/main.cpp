#include <cereal/archives/json.hpp>
#include <cereal/types/string.hpp>
#include <cereal/types/vector.hpp>

#include <iostream>
#include <sstream>
#include <string>
#include <vector>

struct Player {
    std::string name;
    int score;
    std::vector<std::string> tags;

    template <class Archive>
    void serialize(Archive& archive) {
        archive(cereal::make_nvp("name", name),
                cereal::make_nvp("score", score),
                cereal::make_nvp("tags", tags));
    }
};

int main() {
    const Player player{"Ada", 42, {"fast", "accurate"}};

    std::ostringstream out;
    {
        cereal::JSONOutputArchive archive(out);
        archive(cereal::make_nvp("player", player));
    }

    std::cout << out.str() << '\n';
}
