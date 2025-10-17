/**
 * @file receiver_easy.h
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief
 * @version 0.1
 * @date 2025-10-17
 *
 * @copyright Copyright (c) 2025
 *
 */

 #ifndef WIKI_RECEIVER_EASY_H_
#define WIKI_RECEIVER_EASY_H_

#include <algorithm>

#include "receiver.h"

namespace wiki {

class ReceiverEasy : public Receiver {
public:

    /**
     * @brief Construct a new Receiver Easy object
     *
     */
    ReceiverEasy() {
        std::vector<std::string> vals = {"P31"};
        load_dict_list(vals);
    }

    /**
     * @brief Destroy the Receiver Easy object
     *
     */
    virtual ~ReceiverEasy() {
        save();
    }

    /**
     * @brief
     *
     * @return true
     * @return false
     */
    virtual bool save() override {
        return true;
    }

    /**
     * @brief
     *
     * @return true
     * @return false
     */
    virtual bool load() override {
        return true;
    }

    /**
     * @brief
     *
     * @param key
     * @param val
     */
    virtual void put_dictionary_value(const dict_key& key, const dict_val& val) override {
        if(!is_dictionary(key)){
            return;
        }
    }
};

}
#endif
