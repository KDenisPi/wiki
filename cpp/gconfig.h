/**
 * @file gconfig.h
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief
 * @version 0.1
 * @date 2025-12-04
 *
 * @copyright Copyright (c) 2025
 *
 */

#ifndef WIKI_ITEM_GCONFIG_H_
#define WIKI_ITEM_GCONFIG_H_

namespace wiki {

class GConfig {
public:
    GConfig() = default;
    virtual ~GConfig() = default;

    bool debuf_print = true;
    std::vector<std::string> lng = {"ru"};

    /**
     * @brief Get the debug print flag
     *
     * @return true
     * @return false
     */
    inline bool is_debug_print() const {
        return debuf_print;
    }

    /**
     * @brief Get the list of additional languages used for Item loading
     *
     * @return std::vector<std::string>
     */
    inline const std::vector<std::string> get_languages() const {
        return lng;
    }
};

} //namespace wiki
#endif // WIKI_ITEM_GCONFIG_H_