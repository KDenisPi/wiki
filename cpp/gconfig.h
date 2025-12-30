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

    inline static bool debug_print = true;
    std::vector<std::string> lng = {"ru"};

    /**
     * @brief Get the debug print flag
     *
     * @return true
     * @return false
     */
    inline static bool is_debug_print(){
        return debug_print;
    }

    inline static void set_debug_print(const bool dprint){
        debug_print = dprint;
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